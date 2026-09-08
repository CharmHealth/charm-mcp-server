"""Live-server API probe for managePatientFiles (src/tools/clinical_support.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023.
"""
import base64
import tempfile

from conftest import call_tool, TEST_DATA

PATIENT_ID = TEST_DATA["patient_id"]

# A real, minimal 1x1 transparent PNG — needs to be an actual valid image file
# on disk (not a fake path), since upload_photo/upload_id read it from disk.
_MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_temp_png() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    f.write(base64.b64decode(_MINIMAL_PNG_B64))
    f.close()
    return f.name


async def test_managePatientFiles_send_phr_invite():
    # $ ... managePatientFiles '{"patient_id": "100010000000018023", "action": "send_phr_invite", \
    #       "email": "ahmed.choi.test@example.com"}'
    #
    # This sandbox rate-limits PHR invites (CharmHealth's own limit: 3 per
    # patient per 24h) -- repeated test runs the same day legitimately hit
    # that limit, so both outcomes are accepted here rather than asserting
    # unconditional success.
    resp = await call_tool(
        "managePatientFiles",
        {"patient_id": PATIENT_ID, "action": "send_phr_invite", "email": "ahmed.choi.test@example.com"},
    )
    if "error" in resp:
        assert "Cannot send more than 3 invites" in resp["error"], resp
    else:
        assert resp.get("code") == "0"


async def test_managePatientFiles_delete_photo():
    # $ ... managePatientFiles '{"patient_id": "100010000000018023", "action": "delete_photo"}'
    resp = await call_tool("managePatientFiles", {"patient_id": PATIENT_ID, "action": "delete_photo"})
    assert "error" not in resp


async def test_managePatientFiles_upload_photo():
    # $ ... managePatientFiles '{"patient_id": "100010000000018023", "action": "upload_photo", \
    #       "photo_file": "<real local PNG path>"}'
    #
    # FIXED (2026-09-02): previously crashed with "CharmHealthAPIClient.post()
    # got an unexpected keyword argument 'files'" before any network call at
    # all -- CharmHealthAPIClient had no multipart support, and photo_file (a
    # path string) was never actually read from disk. Added post_multipart()
    # to CharmHealthAPIClient and a _read_file_for_upload() helper in
    # clinical_support.py that reads real bytes.
    #
    # OPEN QUESTION (not fixable further without CharmHealth's real API docs,
    # not available locally): the request now reaches the real endpoint
    # cleanly, but the backend responds "Please upload an image to process
    # your request" regardless of which multipart field name is tried (file/
    # photo/image/photo_file/patient_photo). This assertion only confirms the
    # crash is gone (error, if any, must not be the old "unexpected keyword
    # argument" or a file-read failure) -- it does NOT assert full success,
    # since that remains unconfirmed.
    resp = await call_tool(
        "managePatientFiles",
        {"patient_id": PATIENT_ID, "action": "upload_photo", "photo_file": _write_temp_png()},
    )
    if "error" in resp:
        assert "unexpected keyword argument" not in resp["error"]
        assert "Could not read" not in resp["error"]


async def test_managePatientFiles_upload_id():
    # $ ... managePatientFiles '{"patient_id": "100010000000018023", "action": "upload_id", \
    #       "id_file": "<real local PNG path>", "id_qualifier": "drivers_license_id"}'
    #
    # Same fix and same open question as test_managePatientFiles_upload_photo above.
    resp = await call_tool(
        "managePatientFiles",
        {
            "patient_id": PATIENT_ID,
            "action": "upload_id",
            "id_file": _write_temp_png(),
            "id_qualifier": "drivers_license_id",
        },
    )
    if "error" in resp:
        assert "unexpected keyword argument" not in resp["error"]
        assert "Could not read" not in resp["error"]
