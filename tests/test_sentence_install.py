"""Safe installation/update tests for the integration-owned sentence file."""
import tempfile
from pathlib import Path

from custom_components.voice_reminders.sentence_install import install_sentences


def test_sentence_install_lifecycle():
    source_dir = Path(__file__).parents[1] / "custom_components" / "voice_reminders"
    with tempfile.TemporaryDirectory() as config:
        with tempfile.TemporaryDirectory() as package:
            sentence_dir = Path(package) / "sentences" / "ru"
            sentence_dir.mkdir(parents=True)
            source = sentence_dir / "voice_reminders.yaml"
            source.write_text("version one\n")
            target = Path(config) / "custom_sentences" / "ru" / "voice_reminders.yaml"
            marker = target.with_name(".voice_reminders.yaml.sha256")

            assert install_sentences(config, package) == "created"
            assert install_sentences(config, package) == "unchanged"
            source.write_text("version two\n")
            assert install_sentences(config, package) == "updated"
            assert target.read_text() == "version two\n"

            target.write_text("user customization\n")
            assert install_sentences(config, package) == "conflict"
            assert target.read_text() == "user customization\n"

            # Reinstalling the actual bundled grammar creates a fresh managed file.
            target.unlink()
            marker.unlink()
            assert install_sentences(config, str(source_dir)) == "created"


def test_sentence_install_preserves_unmanaged_and_invalid_marker():
    source_dir = Path(__file__).parents[1] / "custom_components" / "voice_reminders"
    with tempfile.TemporaryDirectory() as config:
        target_dir = Path(config) / "custom_sentences" / "ru"
        target_dir.mkdir(parents=True)
        target = target_dir / "voice_reminders.yaml"
        marker = target_dir / ".voice_reminders.yaml.sha256"
        target.write_text("user grammar\n")
        assert install_sentences(config, str(source_dir)) == "conflict"
        assert not marker.exists()
        marker.write_bytes(b"\xff")
        assert install_sentences(config, str(source_dir)) == "conflict"
        assert target.read_text() == "user grammar\n"


def test_sentence_install_preserves_symlinks():
    source_dir = Path(__file__).parents[1] / "custom_components" / "voice_reminders"
    with tempfile.TemporaryDirectory() as config:
        target_dir = Path(config) / "custom_sentences" / "ru"
        target_dir.mkdir(parents=True)
        outside = Path(config) / "user.yaml"
        outside.write_text("user grammar\n")
        target = target_dir / "voice_reminders.yaml"
        target.symlink_to(outside)
        assert install_sentences(config, str(source_dir)) == "conflict"
        assert outside.read_text() == "user grammar\n"
        target.unlink()
        (target_dir / ".voice_reminders.yaml.sha256").symlink_to(outside)
        assert install_sentences(config, str(source_dir)) == "conflict"
        assert not target.exists()
