import torch
import triton
import triton.language as tl


# --- Verbatim from ComfyUI-KJNodes-main\nodes\ltxv_nodes.py (lines 1757-1818) ---
@triton.jit
def _quant_query_per_thread_int8_i64_kernel(Input, Output, Scale, L,
                                            stride_iz, stride_ih, stride_in,
                                            stride_oz, stride_oh, stride_on,
                                            stride_sz, stride_sh,
                                            C: tl.constexpr, BLK: tl.constexpr):
    off_blk = tl.program_id(0) // 8
    off_tld = tl.program_id(0) % 8
    off_h = tl.program_id(1)
    off_b = tl.program_id(2)

    offs_n = off_blk * BLK + tl.arange(0, BLK // 8) * 8 + off_tld
    offs_k = tl.arange(0, C)

    input_ptrs = Input + off_b * stride_iz + off_h * stride_ih + offs_n[:, None].to(tl.int64) * stride_in + offs_k[None, :]
    output_ptrs = Output + off_b * stride_oz + off_h * stride_oh + offs_n[:, None].to(tl.int64) * stride_on + offs_k[None, :]
    scale_ptrs = Scale + off_b * stride_sz + off_h * stride_sh + off_blk * 8 + off_tld

    x = tl.load(input_ptrs, mask=offs_n[:, None] < L)
    x = x.to(tl.float32)
    scale = tl.max(tl.abs(x)) / 127. + 0.0000001
    x_int8 = x / scale
    x_int8 += 0.5 * tl.where(x_int8 >= 0, 1, -1)
    x_int8 = x_int8.to(tl.int8)
    tl.store(output_ptrs, x_int8, mask=offs_n[:, None] < L)
    tl.store(scale_ptrs, scale)


@triton.jit
def _quant_key_per_thread_int8_i64_kernel(Input, Output, Scale, L,
                                          stride_iz, stride_ih, stride_in,
                                          stride_oz, stride_oh, stride_on,
                                          stride_sz, stride_sh,
                                          C: tl.constexpr, BLK: tl.constexpr):
    off_blk = tl.program_id(0) // 4
    off_tld = tl.program_id(0) % 4
    off_h = tl.program_id(1)
    off_b = tl.program_id(2)

    offs_n0 = off_blk * BLK + tl.arange(0, BLK // 8) * 8 + off_tld * 2
    offs_n1 = off_blk * BLK + tl.arange(0, BLK // 8) * 8 + off_tld * 2 + 1
    offs_k = tl.arange(0, C)

    input_ptrs0 = Input + off_b * stride_iz + off_h * stride_ih + offs_n0[:, None].to(tl.int64) * stride_in + offs_k[None, :]
    input_ptrs1 = Input + off_b * stride_iz + off_h * stride_ih + offs_n1[:, None].to(tl.int64) * stride_in + offs_k[None, :]
    output_ptrs0 = Output + off_b * stride_oz + off_h * stride_oh + offs_n0[:, None].to(tl.int64) * stride_on + offs_k[None, :]
    output_ptrs1 = Output + off_b * stride_oz + off_h * stride_oh + offs_n1[:, None].to(tl.int64) * stride_on + offs_k[None, :]
    scale_ptrs = Scale + off_b * stride_sz + off_h * stride_sh + off_blk * 4 + off_tld

    x0 = tl.load(input_ptrs0, mask=offs_n0[:, None] < L)
    x1 = tl.load(input_ptrs1, mask=offs_n1[:, None] < L)
    x0 = x0.to(tl.float32)
    x1 = x1.to(tl.float32)
    scale = max(tl.max(tl.abs(x0)), tl.max(tl.abs(x1))) / 127. + 0.0000001
    x0_int8 = x0 / scale
    x1_int8 = x1 / scale
    x0_int8 += 0.5 * tl.where(x0_int8 >= 0, 1, -1)
    x1_int8 += 0.5 * tl.where(x1_int8 >= 0, 1, -1)
    x0_int8 = x0_int8.to(tl.int8)
    x1_int8 = x1_int8.to(tl.int8)
    tl.store(output_ptrs0, x0_int8, mask=offs_n0[:, None] < L)
    tl.store(output_ptrs1, x1_int8, mask=offs_n1[:, None] < L)
    tl.store(scale_ptrs, scale)


# --- Launch logic verbatim from _per_thread_int8_i64 (ltxv_nodes.py lines 1821-1867) ---
def _per_thread_int8_i64(q, k, BLKQ=128, WARPQ=32, BLKK=64, WARPK=64, tensor_layout="NHD"):
    q_int8 = torch.empty(q.shape, dtype=torch.int8, device=q.device)
    k_int8 = torch.empty(k.shape, dtype=torch.int8, device=k.device)

    if tensor_layout == "NHD":
        b, qo_len, h_qo, head_dim = q.shape
        _, kv_len, h_kv, _ = k.shape
        stride_bz_q, stride_h_q, stride_seq_q = q.stride(0), q.stride(2), q.stride(1)
        stride_bz_qo, stride_h_qo, stride_seq_qo = q_int8.stride(0), q_int8.stride(2), q_int8.stride(1)
        stride_bz_k, stride_h_k, stride_seq_k = k.stride(0), k.stride(2), k.stride(1)
        stride_bz_ko, stride_h_ko, stride_seq_ko = k_int8.stride(0), k_int8.stride(2), k_int8.stride(1)
    else:
        raise ValueError(f"Unknown tensor layout: {tensor_layout}")

    q_scale = torch.empty((b, h_qo, (qo_len + BLKQ - 1) // BLKQ * (BLKQ // WARPQ) * 8), device=q.device, dtype=torch.float32)
    k_scale = torch.empty((b, h_kv, (kv_len + BLKK - 1) // BLKK * (BLKK // WARPK) * 4), device=q.device, dtype=torch.float32)

    grid = ((qo_len + BLKQ - 1) // BLKQ * (BLKQ // WARPQ) * 8, h_qo, b)
    _quant_query_per_thread_int8_i64_kernel[grid](
        q, q_int8, q_scale, qo_len,
        stride_bz_q, stride_h_q, stride_seq_q,
        stride_bz_qo, stride_h_qo, stride_seq_qo,
        q_scale.stride(0), q_scale.stride(1),
        C=head_dim, BLK=WARPQ
    )

    grid = ((kv_len + BLKK - 1) // BLKK * (BLKK // WARPK) * 4, h_kv, b)
    _quant_key_per_thread_int8_i64_kernel[grid](
        k, k_int8, k_scale, kv_len,
        stride_bz_k, stride_h_k, stride_seq_k,
        stride_bz_ko, stride_h_ko, stride_seq_ko,
        k_scale.stride(0), k_scale.stride(1),
        C=head_dim, BLK=WARPK
    )

    return q_int8, q_scale, k_int8, k_scale


q = torch.randn(1, 64, 8, 128, device="cuda", dtype=torch.float16)
k = torch.randn(1, 64, 8, 128, device="cuda", dtype=torch.float16)

q_int8, q_scale, k_int8, k_scale = _per_thread_int8_i64(q, k, tensor_layout="NHD", BLKQ=128, WARPQ=32, BLKK=64, WARPK=64)
torch.cuda.synchronize()
print("KERNEL_LAUNCH_OK", tuple(q_int8.shape), tuple(q_scale.shape), tuple(k_int8.shape), tuple(k_scale.shape))

# spot correctness check: int8 values must be within [-128, 127]
assert q_int8.abs().max().item() <= 127
assert k_int8.abs().max().item() <= 127
print("VALUE_RANGE_OK")
