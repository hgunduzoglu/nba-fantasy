"""Veri girişi: CSV → doğrulanmış tablolar, manifest, ADP fallback (README §5, §6.1)."""

from fdo.ingest.load import Dataset, build_dataset, load_dataset
from fdo.ingest.synthetic import make_synthetic
from fdo.ingest.validate import ValidationReport

__all__ = ["Dataset", "ValidationReport", "build_dataset", "load_dataset", "make_synthetic"]
