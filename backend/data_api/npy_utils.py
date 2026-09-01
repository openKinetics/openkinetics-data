"""Small helpers for inspecting simple NumPy .npy artifacts."""

import ast
import math
import re
import struct
import sys


class NpyReadError(ValueError):
    pass


DTYPE_RE = re.compile(r"^(?P<endian>[<>=|])?(?P<kind>[fiu])(?P<size>\d+)$")
STRUCT_CODES = {
    "f": {2: "e", 4: "f", 8: "d"},
    "i": {1: "b", 2: "h", 4: "i", 8: "q"},
    "u": {1: "B", 2: "H", 4: "I", 8: "Q"},
}


def _product(values):
    total = 1
    for value in values:
        total *= int(value)
    return total


def _parse_dtype(descr):
    if not isinstance(descr, str):
        raise NpyReadError("Structured .npy dtypes are not supported.")
    match = DTYPE_RE.match(descr)
    if not match:
        raise NpyReadError("Unsupported .npy dtype: %s" % descr)

    endian = match.group("endian") or "="
    kind = match.group("kind")
    size = int(match.group("size"))
    code = STRUCT_CODES.get(kind, {}).get(size)
    if not code:
        raise NpyReadError("Unsupported .npy dtype: %s" % descr)

    if endian == "=":
        endian = "<" if sys.byteorder == "little" else ">"
    elif endian == "|":
        endian = "<"
    return endian, code, size


def read_npy_header(path):
    with open(path, "rb") as handle:
        if handle.read(6) != b"\x93NUMPY":
            raise NpyReadError("Not a NumPy .npy file.")
        major, _minor = handle.read(2)
        if major == 1:
            header_length = struct.unpack("<H", handle.read(2))[0]
        elif major in (2, 3):
            header_length = struct.unpack("<I", handle.read(4))[0]
        else:
            raise NpyReadError("Unsupported .npy version: %s" % major)

        header_text = handle.read(header_length).decode("latin1").strip()
        try:
            header = ast.literal_eval(header_text)
        except (SyntaxError, ValueError) as exc:
            raise NpyReadError("Could not parse .npy header.") from exc

        shape = tuple(int(value) for value in header.get("shape") or ())
        descr = header.get("descr")
        _endian, _code, item_size = _parse_dtype(descr)
        return {
            "dtype": descr,
            "shape": list(shape),
            "fortran_order": bool(header.get("fortran_order")),
            "item_count": _product(shape),
            "item_size": item_size,
            "data_offset": handle.tell(),
        }


def read_npy_metadata(path):
    header = read_npy_header(path)
    return {
        "dtype": header["dtype"],
        "shape": header["shape"],
        "fortran_order": header["fortran_order"],
        "item_count": header["item_count"],
    }


def read_npy_flat_numbers(path, max_items=10000):
    header = read_npy_header(path)
    shape = header["shape"]
    if header["fortran_order"] and len(shape) > 1:
        raise NpyReadError("Fortran-ordered matrices are not supported for flat previews.")
    if len(shape) > 2 or (len(shape) == 2 and 1 not in shape):
        raise NpyReadError("Expected a vector-shaped .npy array.")
    if header["item_count"] > max_items:
        raise NpyReadError("Array is too large for an inline preview.")

    endian, code, item_size = _parse_dtype(header["dtype"])
    byte_count = header["item_count"] * item_size
    with open(path, "rb") as handle:
        handle.seek(header["data_offset"])
        data = handle.read(byte_count)
    if len(data) != byte_count:
        raise NpyReadError("Unexpected end of .npy data.")

    values = struct.unpack("%s%s%s" % (endian, header["item_count"], code), data)
    return [
        float(value) if math.isfinite(float(value)) else None
        for value in values
    ]
