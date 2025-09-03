import logging
import os
import sys

import torch
from transformers import AutoConfig, AutoTokenizer
from transformers import (
    HfArgumentParser,
    set_seed,
)
from dataclasses import dataclass, field
from tevatron.retriever.arguments import (
    ModelArguments,
    DataArguments,
    TevatronTrainingArguments,
)
from tevatron.retriever.modeling import SpladeModel
from tevatron.retriever.trainer import TevatronTrainer


from tevatron.retriever.arguments import (
    ModelArguments,
    DataArguments,
    TevatronTrainingArguments as TrainingArguments,
)
from tevatron.retriever.dataset import TrainDataset
from tevatron.retriever.collator import TrainCollator

from tevatron.retriever.trainer import TevatronTrainer as Trainer

logger = logging.getLogger(__name__)


@dataclass
class SpladeTrainingArguments(TevatronTrainingArguments):
    q_flops_loss_factor: float = field(default=4)
    p_flops_loss_factor: float = field(default=32)


class SpladeTrainer(TevatronTrainer):
    @staticmethod
    def _flops(inputs):
        return torch.sum(torch.mean(torch.abs(inputs), dim=0) ** 2)

    def compute_loss(
        self, model, inputs, return_outputs=False, num_items_in_batch=None
    ):
        query, passage = inputs
        output = model(query=query, passage=passage)
        q_reps = output.q_reps
        p_reps = output.p_reps
        loss = output.loss
        q_flops_loss = self.args.q_flops_loss_factor * self._flops(q_reps)
        p_flops_loss = self.args.p_flops_loss_factor * self._flops(p_reps)
        if self.is_ddp:
            q_flops_loss *= self._dist_loss_scale_factor
            p_flops_loss *= self._dist_loss_scale_factor
        return loss + q_flops_loss + p_flops_loss


TrainingArguments = SpladeTrainingArguments


def main():
    parser = HfArgumentParser((ModelArguments, DataArguments, TrainingArguments))

    if len(sys.argv) == 2 and sys.argv[1].endswith(".json"):
        model_args, data_args, training_args = parser.parse_json_file(
            json_file=os.path.abspath(sys.argv[1])
        )
    else:
        model_args, data_args, training_args = parser.parse_args_into_dataclasses()
        model_args: ModelArguments
        data_args: DataArguments
        training_args: TrainingArguments

    if (
        os.path.exists(training_args.output_dir)
        and os.listdir(training_args.output_dir)
        and training_args.do_train
        and not training_args.overwrite_output_dir
    ):
        raise ValueError(
            f"Output directory ({training_args.output_dir}) already exists and is not empty. Use --overwrite_output_dir to overcome."
        )

    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s -   %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        level=logging.INFO if training_args.local_rank in [-1, 0] else logging.WARN,
    )
    logger.warning(
        "Process rank: %s, device: %s, n_gpu: %s, distributed training: %s, 16-bits training: %s",
        training_args.local_rank,
        training_args.device,
        training_args.n_gpu,
        bool(training_args.local_rank != -1),
        training_args.fp16,
    )
    logger.info("Training/evaluation parameters %s", training_args)
    logger.info("MODEL parameters %s", model_args)

    set_seed(training_args.seed)

    tokenizer = AutoTokenizer.from_pretrained(
        (
            model_args.tokenizer_name
            if model_args.tokenizer_name
            else model_args.model_name_or_path
        ),
        cache_dir=model_args.cache_dir,
    )

    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    tokenizer.padding_side = "right"

    model = SpladeModel.build(
        model_args,
        training_args,
        cache_dir=model_args.cache_dir,
        attn_implementation=model_args.attn_implementation,
    )

    train_dataset = TrainDataset(data_args)
    collator = TrainCollator(data_args, tokenizer)

    trainer = SpladeTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=collator,
    )
    train_dataset.trainer = trainer

    trainer.train()  # TODO: resume training
    trainer.save_model()
    if trainer.is_world_process_zero():
        tokenizer.save_pretrained(training_args.output_dir)


if __name__ == "__main__":
    main()
