import torch
import logging
from transformers import Qwen2_5OmniThinkerForConditionalGeneration
from .encoder import EncoderModel

logger = logging.getLogger(__name__)


class DenseModel(EncoderModel):

    def encode_query(self, qry):
        query_hidden_states = self.encoder(**qry, return_dict=True)
        query_hidden_states = query_hidden_states.last_hidden_state
        return self._pooling(query_hidden_states, qry["attention_mask"])

    def encode_passage(self, psg):
        # encode passage is the same as encode query
        return self.encode_query(psg)

    def _pooling(self, last_hidden_state, attention_mask):
        if self.pooling in ["cls", "first"]:
            reps = last_hidden_state[:, 0]
        elif self.pooling in ["mean", "avg", "average"]:
            masked_hiddens = last_hidden_state.masked_fill(
                ~attention_mask[..., None].bool(), 0.0
            )
            reps = masked_hiddens.sum(dim=1) / attention_mask.sum(dim=1)[..., None]
        elif self.pooling in ["last", "eos"]:
            left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
            if left_padding:
                reps = last_hidden_state[:, -1]
            else:
                sequence_lengths = attention_mask.sum(dim=1) - 1
                batch_size = last_hidden_state.shape[0]
                reps = last_hidden_state[
                    torch.arange(batch_size, device=last_hidden_state.device),
                    sequence_lengths,
                ]
        else:
            raise ValueError(f"unknown pooling method: {self.pooling}")
        if self.normalize:
            reps = torch.nn.functional.normalize(reps, p=2, dim=-1)
        return reps


# class MultiModalDenseModel(DenseModel):
#     TRANSFORMER_CLS = Qwen2_5OmniThinkerForConditionalGeneration

#     def __init__(self, encoder, pooling="eos", normalize=True, temperature=0.02):
#         super().__init__(encoder, pooling, normalize, temperature)
#         # freeze visual encoder
#         self.encoder = encoder
#         for param in self.encoder.visual.parameters():
#             param.requires_grad = False
#         # freeze audio_tower
#         for param in self.encoder.audio_tower.parameters():
#             param.requires_grad = False
#         self.config.hidden_size = 3584

#     def gradient_checkpointing_enable(self, **kwargs):
#         self.encoder.model.gradient_checkpointing_enable()

#     def encode_query(self, qry):
#         cache_position = torch.arange(
#             0, qry["input_ids"].shape[1], device=qry["input_ids"].device
#         )
#         qry = self.encoder.prepare_inputs_for_generation(
#             **qry, use_cache=True, cache_position=cache_position
#         )
#         query_hidden_states = self.encoder(
#             **qry, return_dict=True, output_hidden_states=True
#         )
#         # query_hidden_states = query_hidden_states.hidden_states[1][-1]
#         query_hidden_states = query_hidden_states.hidden_states[-1]

#         return self._pooling(query_hidden_states, qry["attention_mask"])

#     def encode_passage(self, psg):
#         # encode passage is the same as encode query
#         return self.encode_query(psg)
