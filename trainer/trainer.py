from typing import Optional, Callable, Any

import torch
from torch.optim import Optimizer
from torch.utils.data import DataLoader

from transformers import BertPreTrainedModel, BertTokenizer

from datetime import datetime

from config import Config
from logs.logger import Logger
from utils.functions import get_token_logits, get_map_location


class Trainer:
    """Model trainer.

    Encapsulates training / validating logic, saving and loading from checkpoints.

    Args:
        model: Training model.
        tokenizer: BERT tokenizer.
        num_labels: Total number of labels.
        loss_fn: Loss function.
        metric_fn: Classification metric function.
        optimizer: GD optimizer.
        config: Training configuration.
        device: Torch device.
        batch_size: Size of batch.
        train_dataloader: Dataloader of train subset.
        valid_dataloader: Dataloader of validation subset.
        lr_scheduler: Learning rate scheduler.
        num_epochs: Total number of epochs.
        logger: Filesystem logger.
    """
    def __init__(
            self,
            model: BertPreTrainedModel,
            tokenizer: BertTokenizer,
            num_labels: int,
            loss_fn: Callable,
            metric_fn: Callable,
            optimizer: Optimizer,
            config: Config,
            device: torch.device,
            batch_size: int,
            train_dataloader: DataLoader,
            valid_dataloader: DataLoader = None,
            lr_scheduler: Any = None,
            num_epochs: int = 1,
            logger: Logger = None
    ):
        self.model = model
        self.tokenizer = tokenizer
        self.num_labels = num_labels
        self.loss_fn = loss_fn
        self.metric_fn = metric_fn
        self.optimizer = optimizer

        self.num_epochs = num_epochs
        self.start_epoch = 0
        self.save_period_in_epochs = config["save_period_in_epochs"]

        self.config = config
        self.device = device

        self.train_dataloader = train_dataloader
        self.valid_dataloader = valid_dataloader
        self.batch_size = batch_size

        self.logger = logger
        self.logger.info("--- New trainer initialized ---", "TRAINER")

        self.lr_scheduler = lr_scheduler

        for metric_name in config["metrics"]:
            setattr(self, f"best_{metric_name}", 0.0)
        self.metrics = {
            "train": {metric_name: [] for metric_name in config["metrics"]},
            "valid": {metric_name: [] for metric_name in config["metrics"]}
        }

        self.losses = {
            "train": [],
            "valid": []
        }

        self.checkpoint_dir = config["checkpoint_dir"]
        if config["start_from_checkpoint"]:
            self._load_checkpoint(self.checkpoint_dir + config["checkpoint_name"])

    def train(self) -> tuple:
        """Train model by epochs.

        Returns:
            tuple: Tuple of losses and metrics during training and validation.
        """
        for epoch in range(self.start_epoch, self.num_epochs):
            self.logger.info(f"Epoch {epoch} started.", "EPOCH")

            train_loss_metric = self._train_epoch()
            self.losses["train"].append(train_loss_metric["loss"])
            self.logger.info(f"Epoch {epoch}. Train loss: {train_loss_metric['loss']}.", "LOSS")

            for metric in train_loss_metric["metrics"].keys():
                self.metrics["train"][metric].append(train_loss_metric["metrics"][metric])
                self.logger.info(
                    f"Epoch {epoch}. {metric}: {train_loss_metric['metrics'][metric]}",
                    "TRAIN_METRICS"
                )

            valid_loss_metric = self._validate_epoch()
            self.losses["valid"].append(valid_loss_metric["loss"])
            self.logger.info(f"Epoch {epoch}. Valid loss: {valid_loss_metric['loss']}.", "LOSS")

            for metric in valid_loss_metric["metrics"].keys():
                self.metrics["valid"][metric].append(valid_loss_metric["metrics"][metric])
                self.logger.info(
                    f"Epoch {epoch}. {metric}: {valid_loss_metric['metrics'][metric]}",
                    "VALID_METRICS"
                )

                if getattr(self, f"best_{metric}") <= valid_loss_metric["metrics"][metric]:
                    setattr(self, f"best_{metric}", valid_loss_metric["metrics"][metric])
                    self.logger.info(
                        f"Epoch {epoch}. New best {metric}: {valid_loss_metric['metrics'][metric]}",
                        "BEST_METRIC"
                    )

                    self._save_checkpoint(
                        epoch,
                        self.losses,
                        self.metrics,
                        save_best=True,
                        suffix=metric
                    )
                    self.logger.info(
                        f"Epoch {epoch}. Model with best {metric}: {valid_loss_metric['metrics'][metric]} saved.",
                        "BEST_SAVED"
                    )

            if epoch % self.save_period_in_epochs == 0:
                Logger.nvidia_smi()

                self._save_checkpoint(
                    epoch,
                    self.losses,
                    self.metrics,
                    save_best=False
                )
                self.logger.info(
                    f"Epoch {epoch}. Model has been saved by periodic saving mechanism.",
                    "PERIODIC_SAVED"
                )
            self.logger.info("--- --- ---", "TRAINER")
        self.logger.info(f"Training successfully ended.", "TRAINER")
        return self.losses, self.metrics

    def _train_epoch(self) -> dict:
        """Train epoch.

        Returns:
            dict: Dictionary of training epoch loss and metrics.
        """
        _logits, _targets = [], []

        self.model.train()

        running_loss = 0.0
        for batch in self.train_dataloader:
            data = batch["data"].to(self.device)
            labels = batch["labels"].to(self.device)

            attention_mask = torch.clone(data != 0)
            logits, = self.model(data, attention_mask=attention_mask)
            cls_logits = get_token_logits(self.device, data, logits, self.tokenizer.cls_token_id)

            loss = self.loss_fn(cls_logits, labels)
            running_loss += loss.item()
            loss.backward()

            self.optimizer.step()
            # model.zero_grad with set_to_none is more efficient
            self.model.zero_grad(set_to_none=True)

            _logits.append(cls_logits.argmax(1).cpu().detach().numpy().tolist())
            _targets.append(labels.cpu().detach().numpy().tolist())

        if self.lr_scheduler is not None:
            self.lr_scheduler.step()
        return {
            "loss": running_loss / self.batch_size,
            "metrics": self.metric_fn(_logits, _targets, self.num_labels)
        }

    def _validate_epoch(self) -> dict:
        """Validate epoch.

        Returns:
            dict: Dictionary of validation epoch loss and metrics.
        """
        _logits, _targets = [], []

        self.model.eval()

        running_loss = 0.0
        with torch.no_grad():
            for batch in self.valid_dataloader:
                data = batch["data"].to(self.device)
                labels = batch["labels"].to(self.device)

                attention_mask = torch.clone(data != 0)
                probs = self.model(data, attention_mask=attention_mask)
                # TODO: why it can return tuple(tensor), except for just tensor?
                if isinstance(probs, tuple):
                    probs = probs[0]
                cls_probs = get_token_logits(self.device, data, probs, self.tokenizer.cls_token_id)

                loss = self.loss_fn(cls_probs, labels)
                running_loss += loss.item()

                _logits.append(cls_probs.argmax(1).cpu().detach().numpy().tolist())
                _targets.append(labels.cpu().detach().numpy().tolist())

        return {
            "loss": running_loss / self.batch_size,
            "metrics": self.metric_fn(_logits, _targets, self.num_labels)
        }

    def _save_checkpoint(
            self,
            epoch: int,
            losses: dict,
            metrics: dict,
            save_best: Optional[bool] = False,
            suffix: Optional[str] = None,
    ) -> None:
        """Save model checkpoint.

        Model is saved in `checkpoints` directory.

        Parameters to be saved:
            - number of epoch
            - model state dict
            - optimizer state dict
            - train/validation losses
            - train/validation metrics
            - current best metrics values

        Args:
            epoch: Number of current epoch.
            losses: Dictionary of model's train / validation losses.
            metrics: Dictionary of model's train / validation metrics.
            save_best: Flag indicating that the model with the best metric is saved.
            suffix: Checkpoint filename suffix.

        Returns:
            None
        """
        if save_best:
            checkpoint_path = (
                f"{self.checkpoint_dir}model_best_{suffix}.pt"
            )
        else:
            checkpoint_path = (
                f"{self.checkpoint_dir}model_epoch_{epoch}_"
                f"datetime-{datetime.now():%d-%m-%y_%H-%M-%S}.pt"
            )
        torch.save(
            {
                "epoch": epoch,
                "model_state_dict": self.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "losses": losses,
                "metrics": metrics,
                "best_metrics": {f"best_{i}": getattr(self, f"best_{i}") for i in self.config["metrics"]},
            },
            checkpoint_path
        )

    def _load_checkpoint(self, checkpoint_path: str) -> None:
        """Load model checkpoint.

        Initialize model from checkpoint for further training.

        Args:
            checkpoint_path: Checkpoint filename in `checkpoints` directory.

        Returns:
            None
        """
        checkpoint = torch.load(checkpoint_path, map_location=get_map_location())

        self.start_epoch = checkpoint["epoch"] + 1

        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])

        for metric_name in self.config["metrics"]:
            setattr(self, f"best_{metric_name}", checkpoint["best_metrics"][f"best_{metric_name}"])
        self.metrics = checkpoint["metrics"]

        self.losses = checkpoint["losses"]
