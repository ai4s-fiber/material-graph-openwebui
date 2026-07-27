from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE_WORKFLOW = ROOT / '.github' / 'workflows' / 'material-graph-image.yml'
CI_WORKFLOW = ROOT / '.github' / 'workflows' / 'material-graph-ci.yml'
FRONTEND_WORKFLOW = ROOT / '.github' / 'workflows' / 'frontend.yaml'


def _text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _assert_actions_are_commit_pinned(path: Path) -> None:
    uses = re.findall(r'^\s*-?\s*uses:\s+[^@\s]+@([^\s#]+)', _text(path), re.MULTILINE)
    assert uses, f'no actions found in {path.name}'
    assert all(re.fullmatch(r'[0-9a-f]{40}', revision) for revision in uses)


def test_release_image_is_non_root_with_a_writable_data_volume() -> None:
    dockerfile = _text(ROOT / 'Dockerfile')

    assert re.search(r'^ARG UID=10001$', dockerfile, re.MULTILINE)
    assert re.search(r'^ARG GID=10001$', dockerfile, re.MULTILINE)
    assert re.search(r'^ARG UV_VERSION=0\.11\.32$', dockerfile, re.MULTILINE)
    assert 'python -m pip install --no-cache-dir "uv==${UV_VERSION}"' in dockerfile
    assert 'test "$UID" -ne 0' in dockerfile
    assert 'test "$GID" -ne 0' in dockerfile
    assert 'install -d -o "$UID" -g "$GID" -m 0750 /app/backend/data' in dockerfile
    assert 'WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key' in dockerfile
    assert 'VOLUME ["/app/backend/data"]' in dockerfile
    assert 'USER $UID:$GID' in dockerfile


def test_release_image_pins_audited_base_images_and_separates_build_tools() -> None:
    dockerfile = _text(ROOT / 'Dockerfile')

    for name in ('NODE_BASE', 'PYTHON_BASE', 'RUST_BASE', 'DEBIAN_BASE'):
        assert re.search(
            rf'^ARG {name}=[^\s]+@sha256:[0-9a-f]{{64}}$',
            dockerfile,
            re.MULTILINE,
        )

    assert 'AS frontend-build' in dockerfile
    assert 'AS rust-toolchain' in dockerfile
    assert 'AS python-deps' in dockerfile
    assert 'AS runtime' in dockerfile
    assert 'backend/requirements-production.lock' in dockerfile
    assert '--require-hashes' in dockerfile
    assert '--no-deps' in dockerfile

    runtime = dockerfile.split('AS runtime', maxsplit=1)[1]
    assert 'apt-get install -y --no-install-recommends libpq5 libxml2 libxslt1.1' in runtime
    assert 'build-essential' not in runtime
    assert 'libpq-dev' not in runtime
    assert 'libxml2-dev' not in runtime
    assert 'libxslt1-dev' not in runtime
    assert 'zlib1g-dev' not in runtime
    for executable in ('git', 'curl', 'jq', 'ffmpeg', 'gcc', 'make', 'cargo', 'rustc'):
        assert f'! command -v {executable}' in runtime


def test_unfixed_dependency_stacks_are_absent_from_production() -> None:
    production_requirements = _text(ROOT / 'backend' / 'requirements-production.txt').lower()
    production_lock = _text(ROOT / 'backend' / 'requirements-production.lock').lower()
    pyproject = _text(ROOT / 'pyproject.toml').lower()
    dockerfile = _text(ROOT / 'Dockerfile').lower()

    for forbidden in ('chromadb', 'python-jose', 'ecdsa', 'psycopg2'):
        assert forbidden not in production_requirements
        assert forbidden not in production_lock
        assert forbidden not in pyproject

    assert 'psycopg-c==3.3.4' in production_lock
    assert "psycopg.pq.__impl__ == 'c'" in dockerfile
    native_import_smoke = 'import aiohttp, fastapi, orjson, pgvector, psycopg, pydantic, sqlalchemy'
    assert dockerfile.count(native_import_smoke) == 2
    assert native_import_smoke in _text(CI_WORKFLOW)
    assert 'zlib1g-dev' in dockerfile
    assert 'vector_db=pgvector' in dockerfile
    assert 'severity-cutoff' not in dockerfile


def test_material_graph_workflows_pin_every_action_to_a_commit() -> None:
    _assert_actions_are_commit_pinned(CI_WORKFLOW)
    _assert_actions_are_commit_pinned(IMAGE_WORKFLOW)


def test_frontend_format_gate_is_read_only_and_project_scoped() -> None:
    workflow = _text(FRONTEND_WORKFLOW)
    formatting = workflow.split('- name: Verify Material Graph formatting', maxsplit=1)[1]
    formatting = formatting.split('- name: Production build', maxsplit=1)[0]

    assert 'npx prettier --check' in formatting
    assert '"src/lib/components/chat/MaterialGraph/**/*.{ts,svelte}"' in formatting
    assert '".github/workflows/material-graph-image.yml"' in formatting
    assert 'npm run format' not in workflow
    assert 'npm run i18n:parse' not in workflow
    assert 'git diff --exit-code' not in workflow
    assert 'npm run build' in workflow


def test_release_blocks_high_vulnerabilities_and_keylessly_signs_the_digest() -> None:
    workflow = _text(IMAGE_WORKFLOW)
    publish = workflow.split('\n  verify-public:', maxsplit=1)[0]

    assert 'anchore/scan-action@' in publish
    assert 'severity-cutoff: high' in publish
    assert 'fail-build: true' in publish
    assert 'sigstore/cosign-installer@' in publish
    assert 'cosign sign --yes "${IMAGE_NAME}@${{ steps.build.outputs.digest }}"' in publish
    assert 'UID=10001' in publish
    assert 'GID=10001' in publish
    assert 'UV_VERSION=0.11.32' in publish


def test_pull_requests_use_the_same_high_severity_container_gate() -> None:
    workflow = _text(CI_WORKFLOW)

    assert 'container-security:' in workflow
    assert 'docker/build-push-action@' in workflow
    assert 'anchore/scan-action@' in workflow
    assert 'severity-cutoff: high' in workflow
    assert 'fail-build: true' in workflow
    assert 'only-fixed: false' in workflow
    assert 'Smoke-test the production application' in workflow
    assert 'http://127.0.0.1:18080/health' in workflow


def test_public_pull_and_signature_are_verified_in_an_independent_job() -> None:
    workflow = _text(IMAGE_WORKFLOW)
    assert '\n  verify-public:\n' in workflow
    publish, verify = workflow.split('\n  verify-public:\n', maxsplit=1)

    assert 'Verify anonymous public pull' not in publish
    assert 'needs: publish' in verify
    assert re.search(r'permissions:\s*\n\s+contents: read', verify)
    assert 'packages: write' not in verify
    assert 'id-token: write' not in verify
    assert 'docker/login-action@' not in verify
    assert 'DOCKER_CONFIG' in verify
    assert 'ghcr.io/token?service=ghcr.io' in verify
    assert 'docker-content-digest' in verify
    assert 'cosign verify' in verify
    assert '--certificate-identity' in verify
    assert '--certificate-oidc-issuer' in verify
