import torch
from torch import Tensor
from torcheval.metrics.functional import multiclass_f1_score


def multiple_f1_score(output, target) -> tuple[Tensor, Tensor, Tensor]:
    """TODO"""
    # TODO: memory cpy here, may be bad.
    logits_tensor = torch.flatten(torch.tensor(output))
    targets_tensor = torch.flatten(torch.tensor(target))
    f1_micro = multiclass_f1_score(
        logits_tensor,
        targets_tensor,
        num_classes=339,
        average="micro"
    )
    # TODO: useless if has class imbalance
    f1_macro = multiclass_f1_score(
        logits_tensor,
        targets_tensor,
        num_classes=339,
        average="macro"
    )
    f1_weighted = multiclass_f1_score(
        logits_tensor,
        targets_tensor,
        num_classes=339,
        average="weighted"
    )

    return f1_micro, f1_macro, f1_weighted