from typing import Optional, Type

from collections import OrderedDict

import numpy as np
import torch

import matplotlib.pyplot as plt

from config import Config
from dataset.colwise_dataset import ColWiseDataset
from dataset.dataset import TableDataset
from dataset.single_column_dataset import SingleColumnDataset


def collate(samples: list) -> dict:
    """Preprocess data by batch.

    Pad sequence by length of maximum sequence in a batch with zeros.

    Flatten labels into one sequence.

    Args:
        samples: Samples from batch.

    Returns:
        dict: Padded sequences and flattened labels.
    """
    data = torch.nn.utils.rnn.pad_sequence(
        [sample["data"] for sample in samples]
    )
    labels = torch.cat([sample["labels"] for sample in samples])

    batch = {"data": data.T, "labels": labels}
    return batch


def prepare_device(n_gpu_use: int) -> tuple[torch.device, list]:
    """Prepare GPUs for training.

    Note:
        Supports multiple GPUs.

    Args:
        n_gpu_use: Number of GPUs to prepare.

    Returns:
        tuple: Device and list of available GPUs, if machine have multiple GPUs available.
    """
    num_gpu = torch.cuda.device_count()
    if n_gpu_use > 0 and num_gpu == 0:
        print("Warning: No GPU available on this machine, training will be performed on CPU.")
        n_gpu_use = 0
    if n_gpu_use > num_gpu:
        print(f"Warning: The number of GPU configured to use is {n_gpu_use}, but only {num_gpu} are available")
        n_gpu_use = num_gpu
    device = torch.device('cuda:0' if n_gpu_use > 0 else 'cpu')
    list_ids = list(range(n_gpu_use))
    return device, list_ids


def get_token_logits(device: torch.device, data: torch.Tensor, logits: torch.Tensor, token_id: int) -> torch.Tensor:
    """Get specific token logits in the data.

    Args:
        device: Device (GPU or CPU).
        data: Model input data.
        logits: Model logits.
        token_id: Token id.

    Returns:
        torch.Tensor: All specific token logits in data.
    """
    token_indexes = torch.nonzero(data == token_id)
    token_logits = torch.zeros(
        token_indexes.shape[0],
        logits.shape[2]
    ).to(device)

    for i in range(token_indexes.shape[0]):
        j, k = token_indexes[i]
        logit_i = logits[j, k, :]
        token_logits[i] = logit_i
    return token_logits


def plot_graphs(losses: dict, metrics: dict, config: Config) -> None:
    """Plot training graphics.

    Args:
        losses: Dictionary of training / validation losses by epoch.
        metrics: Dictionary of training / validation metrics by epoch.
        config: Training configuration.

    Returns:
        None
    """
    tr_loss, vl_loss = losses["train"], losses["valid"]

    plt.plot(tr_loss)
    plt.plot(vl_loss)
    plt.legend(["Train loss", "Valid loss"])
    plt.show()

    for metric in config["metrics"]:
        tr_f1, vl_f1 = metrics["train"][metric], metrics["valid"][metric]
        plt.plot(tr_f1)
        plt.plot(vl_f1)
        plt.legend([f"Train {metric}", f"Valid {metric}"])
        plt.show()


def set_rs(seed: int = 13) -> None:
    """Set random seed.

    Args:
        seed: Random seed.

    Returns:
        None
    """
    # Random seed
    torch.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)


def get_map_location() -> Optional[torch.device]:
    """Get device to perform model loading.

    Returns:
        Optional[torch.device]: device to perform load function.
    """
    map_location = None
    if not torch.cuda.is_available():
        map_location = torch.device("cpu")
    return map_location


def filter_model_state_dict(model_state_dict: dict) -> OrderedDict:
    """Filter model state dict keys.

    Filters model state dict keys after training with torch.DataParallel on multiple GPUs.

    Args:
        model_state_dict: PyTorch model state dictionary.

    Returns:
        OrderedDict: model state dict without `model` in keys, inserted by torch.DataParallel
    """
    filtered_model_state_dict = OrderedDict()
    for k, v in model_state_dict.items():
        if k.startswith("module."):
            filtered_model_state_dict[k[7:]] = v
        else:
            filtered_model_state_dict[k] = v
    return filtered_model_state_dict


def get_dataset_type(table_serialization_strategy: str) -> Type[TableDataset | ColWiseDataset | SingleColumnDataset]:
    """Get type of dataset by strategy.

    Note:
        Available table serialization strategy names:
            - *table_wise*
            - *column_wise*
            - *single_column*

    Args:
        table_serialization_strategy: Name of strategy.

    Returns:
        Type: Type of dataset, if undefined returns `table_wise` dataset.
    """
    table_serialization_type_dataset = {
        "table_wise": TableDataset,
        "column_wise": ColWiseDataset,
        "single_column": SingleColumnDataset
    }

    dataset = table_serialization_type_dataset.get(
        table_serialization_strategy,
        TableDataset
    )
    return dataset
