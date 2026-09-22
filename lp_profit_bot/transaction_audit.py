"""Inspect XDEX swap bounds without signing or sending a transaction.

This is an initial execution gate, not a complete transaction validator.
"""

import base64
import hashlib
import struct

SWAP_BASE_INPUT = hashlib.sha256(b"global:swap_base_input").digest()[:8]
XDEX_PROGRAM = "sEsYH97wqmfnkzHedjNcw3zyJdPvUmsa9AixhS4b4fN"
COMPUTE_PROGRAM = "ComputeBudget111111111111111111111111111111"


class AuditError(ValueError):
    pass


def base58(data: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    value = int.from_bytes(data, "big")
    result = ""
    while value:
        value, digit = divmod(value, 58)
        result = alphabet[digit] + result
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + result


def swap_bounds(data: bytes) -> dict:
    if len(data) != 24 or data[:8] != SWAP_BASE_INPUT:
        raise AuditError("Unknown swap instruction layout")
    amount_in, minimum_out = struct.unpack("<QQ", data[8:])
    if amount_in == 0:
        raise AuditError("Swap input is zero")
    return {"amount_in_raw": amount_in, "minimum_out_raw": minimum_out,
            "output_protected": minimum_out > 0}


def audit_prepared(encoded: str, expected_wallet: str) -> dict:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise AuditError("Invalid transaction encoding") from None
    offset = 0

    def take(size):
        nonlocal offset
        if offset + size > len(raw):
            raise AuditError("Truncated transaction")
        result = raw[offset:offset + size]
        offset += size
        return result

    def short():
        result = 0
        for shift in (0, 7, 14):
            value = take(1)[0]
            result |= (value & 127) << shift
            if value < 128:
                return result
        raise AuditError("Invalid compact integer")

    signatures = short()
    take(signatures * 64)
    if take(1)[0] != 128:
        raise AuditError("Only version-0 transactions are supported by this audit")
    header = take(3)
    if signatures != 1 or header[0] != 1:
        raise AuditError("Unexpected additional signers")
    keys = [base58(take(32)) for _ in range(short())]
    if not keys or keys[0] != expected_wallet:
        raise AuditError("Fee payer does not match the configured wallet")
    take(32)  # Recent blockhash.
    instructions = []
    for _ in range(short()):
        program = take(1)[0]
        accounts = list(take(short()))
        data = take(short())
        instructions.append((program, accounts, data))
    if short() != 0:
        raise AuditError("Address lookup tables require resolution before audit")
    if offset != len(raw):
        raise AuditError("Unexpected trailing transaction bytes")
    swaps = []
    for program, accounts, data in instructions:
        if program >= len(keys) or any(index >= len(keys) for index in accounts):
            raise AuditError("Invalid account index")
        if keys[program] == COMPUTE_PROGRAM:
            continue
        if keys[program] != XDEX_PROGRAM:
            raise AuditError("Instruction requires additional program validation")
        if len(accounts) != 13 or accounts[0] != 0:
            raise AuditError("Unexpected swap accounts")
        bounds = swap_bounds(data)
        bounds.update(pool=keys[accounts[3]], input_mint=keys[accounts[10]],
                      output_mint=keys[accounts[11]])
        swaps.append(bounds)
    if not swaps:
        raise AuditError("No supported swaps found")
    return {"swaps": swaps, "zero_minimum_output": any(not s["output_protected"] for s in swaps),
            "execution_allowed": False,
            "reason": "Full atomic-route validation and local signing are not implemented"}
