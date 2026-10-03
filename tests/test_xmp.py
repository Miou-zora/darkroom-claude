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


def test_crop_aspect_sets_the_ratio_fields():
    f = lambda *a, **k: struct.unpack("<4f2i", xmp.crop_params(*a, **k))[4:]
    assert f(0, 0, 0.5, 0.5, aspect=(4, 5)) == (4, 5)   # (n, d), 4:5 crop of a portrait input
    assert f(0, 0, 0.5, 0.5, aspect=(8, 10)) == (4, 5)  # reduced
    assert f(0, 0, 1, 1, aspect=(3, 2)) == (2, 3)         # landscape 3:2 on a landscape input (issue #11)
    assert f(0, 0, 0.9, 0.9, aspect=(4, 3)) == (3, 4)     # 4:3 crop of a 4:3 input
    assert f(0, 0, 1, 1, aspect=(1, 1)) == (1, 1)
    assert f(0, 0, 1, 1) == (0, 0)                         # freehand by default


def test_crop_aspect_sign_follows_the_input_orientation():
    f = lambda *a, **k: struct.unpack("<4f2i", xmp.crop_params(*a, **k))[4:]
    # 4:3 landscape crop of a 2:3 portrait input: full width, half the height (issue #11: 3,-4)
    assert f(0, 0.25, 1, 0.75, aspect=(4, 3)) == (3, -4)
    # 4:5 portrait crop of a 3:2 landscape input
    assert f(0, 0, 0.5333, 1, aspect=(4, 5)) == (4, -5)


def test_crop_aspect_refuses_a_second_source():
    with pytest.raises(ValueError):
        xmp.crop_params(0, 0, 1, 1, ratio_n=1, ratio_d=2, aspect=(4, 5))
    with pytest.raises(ValueError):
        xmp.crop_params(0, 0, 1, 1, aspect=(0, 5))
