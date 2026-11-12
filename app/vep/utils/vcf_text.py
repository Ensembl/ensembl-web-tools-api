"""How the results VCF is decoded.

VCF is UTF-8, but VEP copies header lines through unchanged, so an output VCF
can hold bytes that are not. Those bytes are dropped.
"""

VCF_TEXT = {"encoding": "utf-8", "errors": "ignore"}
