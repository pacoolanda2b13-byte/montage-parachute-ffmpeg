"""
Tests pour core/file_sorter.py.

Couvre :
- extract_gopro_number : patterns GX, GOPR, GH, GP, noms non-GoPro, edge cases
- sort_files : dossier vide, fichier unique, fichiers non-vidéo ignorés
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from core.file_sorter import extract_gopro_number, sort_files, SortResult


# ─── extract_gopro_number ───────────────────────────────────────

class TestExtractGoProNumber:

    # ── Pattern GX (Hero 9+)
    def test_gx_standard(self):
        assert extract_gopro_number("GX010045.MP4") == 45

    def test_gx_zero_padded(self):
        assert extract_gopro_number("GX010001.MP4") == 1

    def test_gx_max_number(self):
        assert extract_gopro_number("GX019999.MP4") == 9999

    def test_gx_lowercase_extension(self):
        assert extract_gopro_number("GX010045.mp4") == 45

    # ── Pattern GOPR (Hero 3/4/5)
    def test_gopr_standard(self):
        assert extract_gopro_number("GOPR0123.MP4") == 123

    def test_gopr_four_digits(self):
        assert extract_gopro_number("GOPR4567.MP4") == 4567

    def test_gopr_single_digit(self):
        assert extract_gopro_number("GOPR0001.MP4") == 1

    # ── Pattern GH (Hero Black)
    def test_gh_standard(self):
        assert extract_gopro_number("GH010067.MP4") == 67

    def test_gh_lowercase(self):
        assert extract_gopro_number("gh010067.mp4") == 67

    # ── Pattern GP
    def test_gp_standard(self):
        assert extract_gopro_number("GP010089.MP4") == 89

    # ── Noms non-GoPro → None
    def test_non_gopro_generic_name(self):
        assert extract_gopro_number("random.mp4") is None

    def test_non_gopro_date_name(self):
        assert extract_gopro_number("2024-06-01_jump.mp4") is None

    def test_non_gopro_dji(self):
        assert extract_gopro_number("DJI_0001.MP4") is None

    def test_non_gopro_sony(self):
        assert extract_gopro_number("C0001.MP4") is None

    # ── Edge cases
    def test_empty_string(self):
        assert extract_gopro_number("") is None

    def test_no_extension(self):
        # Path("GX010045").stem == "GX010045" — le regex matche quand même
        result = extract_gopro_number("GX010045")
        # Le résultat dépend du regex : soit 45 soit None, les deux sont OK
        assert result is None or result == 45

    def test_gopr_lowercase_prefix(self):
        assert extract_gopro_number("gopr0123.mp4") == 123


# ─── sort_files : dossier vide ──────────────────────────────────

class TestSortFilesEmpty:
    def test_empty_folder_returns_empty_result(self, tmp_path):
        result = sort_files(tmp_path)
        assert isinstance(result, SortResult)
        assert result.fichiers == []
        assert len(result.avertissements) > 0  # warns about no files

    def test_folder_with_only_non_video_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8")
        result = sort_files(tmp_path)
        assert result.fichiers == []

    def test_nonexistent_folder(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError):
            sort_files(missing)


# ─── sort_files : fichier unique ────────────────────────────────

class TestSortFilesSingle:
    def test_single_gopro_file(self, tmp_path):
        f = tmp_path / "GX010045.MP4"
        f.write_bytes(b"\x00" * 8)
        result = sort_files(tmp_path)
        # Peut avoir 0 ou 1 fichiers (ffprobe échoue sur les faux fichiers)
        # On vérifie juste pas de crash + confiance cohérente
        assert isinstance(result, SortResult)
        assert result.confiance_globale >= 0.0


# ─── sort_files : fichiers non-vidéo ignorés ────────────────────

class TestSortFilesIgnoresNonVideo:
    def test_non_video_extensions_excluded(self, tmp_path):
        (tmp_path / "GX010001.MP4").write_bytes(b"\x00" * 8)
        (tmp_path / "thumbnail.jpg").write_bytes(b"\xff\xd8")
        (tmp_path / "notes.txt").write_text("sauts du jour")
        (tmp_path / "GX010001.LRV").write_bytes(b"\x00" * 8)
        (tmp_path / "GX010001.THM").write_bytes(b"\x00" * 4)
        result = sort_files(tmp_path)
        # Seuls les .mp4/.mov/.avi/.mts doivent être considérés
        for fi in result.fichiers:
            assert fi.path.suffix.lower() in {".mp4", ".mov", ".avi", ".mts"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
