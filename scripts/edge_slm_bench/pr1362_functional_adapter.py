"""Export adapter copied from mindspore-lite PR1362, a6cd83f6a6d4fc8afe426f153d63491fe4a7bb50.
Only the functional adapter is reused for ordinary Qwen3; no speculative decoding.
"""
import torch
from mslite_llm_ops import MsTransRopeScatterNDUpdate

# Torch export requires forward/symbolic only; differentiation and vmap are unsupported.
class MsTransRopeScatterNDUpdateFunctional(torch.autograd.Function):  # pylint: disable=abstract-method
    """Export-only functional cache interface, lowered before device compilation.

    Keeps cache edges explicit through ONNX optimizations. The three-output
    symbolic is not a device ABI: exporters must lower it to the mutable,
    single-output operator after validating its attention consumers.
    """

    @staticmethod
    def forward(ctx, q, k, v, cos, sin, kcache, vcache, indices,  # pylint: disable=arguments-differ
                num_attention_heads=None, rotary_dim=None):
        """Evaluate without modifying caller-owned caches; inference only."""
        del ctx
        next_key, next_value = kcache.detach().clone(), vcache.detach().clone()
        query = MsTransRopeScatterNDUpdate.forward(
            None, q.detach(), k.detach(), v.detach(), cos.detach(), sin.detach(),
            next_key, next_value, indices, num_attention_heads, rotary_dim,
        )
        return query, next_key, next_value

    @staticmethod
    def symbolic(g, q, k, v, cos, sin, kcache, vcache, indices,
                 num_attention_heads=None, rotary_dim=None):
        """Retain data dependencies until the writable-cache lowering pass."""
        batch, seq, heads, dim = q.type().sizes()
        query, key, value = g.op(
            "custom::MsTransRopeScatterNDUpdate", q, k, v, cos, sin, kcache, vcache, indices,
            num_attention_heads_i=int(num_attention_heads if num_attention_heads is not None else heads),
            rotary_dim_i=int(rotary_dim if rotary_dim is not None else cos.type().sizes()[-1]),
            storage_layout_s="ND", outputs=3,
        )
        query.setType(q.type().with_sizes([batch, heads, seq, dim]))
        key.setType(kcache.type())
        value.setType(vcache.type())
        return query, key, value

