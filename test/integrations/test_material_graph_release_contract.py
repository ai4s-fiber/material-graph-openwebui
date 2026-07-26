from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMAGE_WORKFLOW = ROOT / ".github" / "workflows" / "material-graph-image.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "material-graph-ci.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_actions_are_commit_pinned(path: Path) -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s+[^@\s]+@([^\s#]+)", _text(path), re.MULTILINE)
    assert uses, f"no actions found in {path.name}"
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in uses)


def test_release_image_is_non_root_with_a_writable_data_volume() -> None:
    dockerfile = _text(ROOT / "Dockerfile")

    assert re.search(r"^ARG UID=10001$", dockerfile, re.MULTILINE)
    assert re.search(r"^ARG GID=10001$", dockerfile, re.MULTILINE)
    assert re.search(r"^ARG UV_VERSION=0\.11\.32$", dockerfile, re.MULTILINE)
    assert 'pip3 install --no-cache-dir "uv==${UV_VERSION}"' in dockerfile
    assert 'test "$UID" -ne 0' in dockerfile
    assert 'test "$GID" -ne 0' in dockerfile
    assert (
        'install -d -o "$UID" -g "$GID" -m 0750 /app/backend/data' in dockerfile
    )
    assert 'VOLUME ["/app/backend/data"]' in dockerfile
    assert "USER $UID:$GID" in dockerfile


def test_material_graph_workflows_pin_every_action_to_a_commit() -> None:
    _assert_actions_are_commit_pinned(CI_WORKFLOW)
    _assert_actions_are_commit_pinned(IMAGE_WORKFLOW)


def test_release_blocks_high_vulnerabilities_and_keylessly_signs_the_digest() -> None:
    workflow = _text(IMAGE_WORKFLOW)
    publish = workflow.split("\n  verify-public:", maxsplit=1)[0]

    assert "anchore/scan-action@" in publish
    assert "severity-cutoff: high" in publish
    assert "fail-build: true" in publish
    assert "sigstore/cosign-installer@" in publish
    assert 'cosign sign --yes "${IMAGE_NAME}@${{ steps.build.outputs.digest }}"' in publish
    assert "UID=10001" in publish
    assert "GID=10001" in publish
    assert "UV_VERSION=0.11.32" in publish


def test_public_pull_and_signature_are_verified_in_an_independent_job() -> None:
    workflow = _text(IMAGE_WORKFLOW)
    assert "\n  verify-public:\n" in workflow
    publish, verify = workflow.split("\n  verify-public:\n", maxsplit=1)

    assert "Verify anonymous public pull" not in publish
    assert "needs: publish" in verify
    assert re.search(r"permissions:\s*\n\s+contents: read", verify)
    assert "packages: write" not in verify
    assert "id-token: write" not in verify
    assert "docker/login-action@" not in verify
    assert "DOCKER_CONFIG" in verify
    assert "ghcr.io/token?service=ghcr.io" in verify
    assert "docker-content-digest" in verify
    assert "cosign verify" in verify
    assert "--certificate-identity" in verify
    assert "--certificate-oidc-issuer" in verify
