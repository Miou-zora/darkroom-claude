import base64, struct, zlib
import pytest
import xmp


def test_decode_hex_and_gz_roundtrip():
    raw = bytes(range(40))
    assert xmp.decode_blob(raw.hex()) == raw
    gz = "gz12" + base64.b64encode(zlib.compress(raw)).decode()
    assert xmp.decode_blob(gz) == raw


def test_neutral_blend_decodes_to_mask_off():
    b = xmp.decode_blob(xmp.NEUTRAL_BLEND)
    assert struct.unpack("<I", b[:4])[0] == 0          # mask_mode 0 = no mask


def test_append_increments_history(minimal_xmp):
    x = xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(1.0))
    x = xmp.append(x, "crop", 3, xmp.crop_params(0.1, 0.1, 0.9, 0.9))
    ents = xmp.entries(x)
    assert xmp.history_end(x) == 2 == len(ents)
    assert [e["num"] for e in ents] == ["0", "1"]
    assert [e["operation"] for e in ents] == ["exposure", "crop"]


def test_params_written_lowercase(minimal_xmp):
    x = xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(1.0))
    p = xmp.entries(x)[0]["params"]
    assert p == p.lower() and xmp.decode_blob(p) == xmp.exposure_params(1.0)


@pytest.mark.pitfall("P8")
def test_append_refuses_truncated_history(minimal_xmp):
    x = xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(1.0))
    x = x.replace('darktable:history_end="1"', 'darktable:history_end="0"')
    with pytest.raises(ValueError):
        xmp.append(x, "crop", 3, xmp.crop_params(0, 0, 1, 1))


def test_struct_sizes_match_darktable_5_6():
    assert len(xmp.crop_params(0, 0, 1, 1)) == 24
    assert len(xmp.exposure_params(0.7)) == 28


def test_iop_order_list_insert_then_replace(minimal_xmp):
    x = xmp.with_iop_order_list(minimal_xmp, "a,0,b,0")
    assert 'darktable:iop_order_list="a,0,b,0"' in x
    x = xmp.with_iop_order_list(x, "a,0,b,0,b,1")
    assert x.count("iop_order_list") == 1 and 'iop_order_list="a,0,b,0,b,1"' in x


def test_cli_check_warns_on_multi_instance_without_list(tmp_path, minimal_xmp, capsys):
    x = xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(1.0), multi_priority=1)
    p = tmp_path / "a.xmp"; p.write_text(x)
    assert xmp.main(["xmp.py", "check", str(p)]) == 0
    assert "WARNING" in capsys.readouterr().out
