"""
Tests pour le module telemetry_gopro.

Couvre :
- Filtrage altitudes aberrantes
- Détection chute_start via altitude max
- _decode_values robuste face à GPMF corrompu
- analyze_skydive sur samples vides
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from core.telemetry_gopro import (
    TelemetrySample, analyze_skydive, _decode_values
)


def _make_sample(t, alt=None, speed_3d=None, accel=None):
    return TelemetrySample(
        time_s=t, altitude_m=alt, speed_3d_mps=speed_3d, accel_g=accel,
    )


# ─── analyze_skydive ───────────────────────────────────────────
def test_analyze_skydive_samples_vides():
    """Liste vide -> SkydiveAnalysis vide propre, pas de crash."""
    a = analyze_skydive([])
    assert a.telemetry_disponible is False
    assert a.altitude_max_m is None
    assert a.chute_start_s is None


def test_analyze_skydive_filtre_altitudes_aberrantes():
    """Altitudes aberrantes (-500m, 15000m) doivent etre ignorees."""
    samples = [
        _make_sample(0, alt=100),
        _make_sample(1, alt=-800),  # aberrant (< -100)
        _make_sample(2, alt=15000),  # aberrant (> 12000)
        _make_sample(3, alt=4000),
        _make_sample(4, alt=200),
    ]
    a = analyze_skydive(samples)
    # Les 2 aberrants sont filtres : alt_max=4000, alt_min=100
    assert a.altitude_max_m == 4000.0
    assert a.altitude_min_m == 100.0


def test_analyze_skydive_chute_start_via_altitude_max():
    """chute_start = timestamp ou altitude atteint 95% du max."""
    samples = [
        _make_sample(0, alt=100),     # decollage
        _make_sample(60, alt=2000),    # montee
        _make_sample(120, alt=3800),   # palier (95% de 4000)
        _make_sample(125, alt=4000),   # max
        _make_sample(180, alt=2000),   # chute
    ]
    a = analyze_skydive(samples)
    # 95% de 4000 = 3800, atteint a t=120
    assert a.chute_start_s is not None
    assert 119 <= a.chute_start_s <= 121


# ─── _decode_values ─────────────────────────────────────────────
def test_decode_values_payload_vide():
    """Payload vide -> liste vide, pas de crash."""
    out = _decode_values(b"", b"l", elem_size=4, repeat=10)
    assert out == []


def test_decode_values_repeat_enorme_payload_court():
    """repeat=65535 mais payload de 8 octets : ne doit pas crasher
    ni boucler 65535 fois inutilement (protection GPMF corrompu)."""
    out = _decode_values(b"\x00" * 8, b"l", elem_size=4, repeat=65535)
    assert len(out) == 2  # 8 octets / 4 = 2 elements max
    assert all(v == 0 for v in out)


def test_decode_values_type_inconnu():
    """Type byte inconnu -> liste vide, pas crash."""
    out = _decode_values(b"\x00" * 8, b"X", elem_size=4, repeat=2)
    assert out == []


def test_decode_values_elem_size_zero():
    """elem_size=0 -> liste vide, pas de division par zero."""
    out = _decode_values(b"\x00" * 8, b"l", elem_size=0, repeat=5)
    assert out == []


# ─── Edge cases analyze_skydive ────────────────────────────────
def test_analyze_skydive_pas_de_gps_que_accel():
    """Pas d'altitude GPS mais accel : pipeline continue, juste sans
    chute_start_s telemetrie."""
    samples = [
        _make_sample(0, accel=1.0),
        _make_sample(60, accel=0.3),  # chute libre
        _make_sample(120, accel=0.4),  # chute libre
        _make_sample(180, accel=2.5),  # ouverture
    ]
    a = analyze_skydive(samples)
    assert a.telemetry_disponible is True
    assert a.altitude_max_m is None  # pas de GPS
    # chute_start_s est None car derive d'altitude
    assert a.chute_start_s is None
    # Mais duree_chute_libre detectee via accel
    assert a.duree_chute_libre_s is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
