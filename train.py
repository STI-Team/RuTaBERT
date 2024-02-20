import numpy as np
import torch

from dataset.dataloader import CtaDataLoader
from dataset.dataset import TableDataset
from model.metric import multiple_f1_score
from model.model import BertForClassification

from transformers import BertTokenizer, BertConfig

import matplotlib.pyplot as plt

from config import Config
from trainer.trainer import Trainer
from utils.functions import prepare_device, collate

# Random seed
torch.manual_seed(13)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
np.random.seed(13)


def train(config: Config):
    # TODO: assert config variables assigned and correct
    tokenizer = BertTokenizer.from_pretrained(config["pretrained_model_name"])

    dataset = TableDataset(
        tokenizer=tokenizer,
        num_rows=config["dataset"]["num_rows"],
        data_dir=config["dataset"]["data_dir"]
    )
    train_dataloader = CtaDataLoader(
        dataset,
        batch_size=config["batch_size"],
        num_workers=config["dataloader"]["num_workers"],
        split=config["dataloader"]["valid_split"],
        collate_fn=collate
    )
    valid_dataloader = train_dataloader.get_valid_dataloader()

    model = BertForClassification(
        BertConfig.from_pretrained(config["pretrained_model_name"], num_labels=config["num_labels"])
    )

    # TODO: multi-gpu support!
    device, device_ids = prepare_device(config["num_gpu"])
    model = model.to(device)
    if len(device_ids) > 1:
        model = torch.nn.DataParallel(model, device_ids=device_ids)

    trainer = Trainer(
        model,
        tokenizer,
        config["num_labels"],
        torch.nn.CrossEntropyLoss(),
        multiple_f1_score,
        torch.optim.AdamW(model.parameters()),
        config,
        device,
        config["batch_size"],
        train_dataloader,
        valid_dataloader,
        num_epochs=config["num_epochs"],
    )

    return trainer.train()


if __name__ == "__main__":
    losses, metrics = train(Config(config_path="config.json"))

    tr_loss, vl_loss = losses["train"], losses["valid"]
    plt.plot(tr_loss)
    plt.plot(vl_loss)
    plt.legend(["Train loss", "Valid loss"])
    plt.show()

    for metric in ["f1_micro", "f1_macro", "f1_weighted"]:
        tr_f1, vl_f1 = metrics["train"][metric], metrics["valid"][metric]
        plt.plot(tr_f1)
        plt.plot(vl_f1)
        plt.legend([f"Train {metric}", f"Valid {metric}"])
        plt.show()
