"""tools/modules.json is data the KPIs and the accessors both trust: check it against itself."""
import os, re, struct
import pytest
import xmp

MODS = {k: v for k, v in xmp.LAYOUTS.items() if not k.startswith("_")}
HERE = os.path.dirname(__file__)


@pytest.mark.parametrize("module", MODS)
def test_layout_size_matches_fields(module):
    m = MODS[module]
    assert struct.calcsize("<" + "".join(f["type"] for f in m["fields"])) == m["size"]
    names = [f["name"] for f in m["fields"]]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("module", MODS)
def test_confirming_tests_exist(module):
    """A `test` that names nothing would never count as confirmed, and nobody would notice."""
    for f in MODS[module]["fields"]:
        if f["test"]:
            path, name = f["test"].split("::")
            assert re.search(rf"^def {name}\(", open(os.path.join(HERE, "..", path)).read(), re.M), f


def test_default_params_roundtrip():
    b = xmp.default_params("colorbalancergb", 5)
    assert len(b) == 132
    assert xmp.get_field(b, "colorbalancergb", 5, "grey_fulcrum") == pytest.approx(0.1845)
    assert xmp.get_field(b, "colorbalancergb", 5, "saturation_formula") == 1


def test_set_field_changes_only_that_field():
    b = xmp.default_params("sigmoid", 3)
    c = xmp.set_field(b, "sigmoid", 3, "contrast_skewness", 0.5)
    assert xmp.get_field(c, "sigmoid", 3, "contrast_skewness") == pytest.approx(0.5)
    assert len(c) == len(b) and b[:4] == c[:4] and b[8:] == c[8:]


def test_accessors_agree_with_the_hand_written_builders():
    assert xmp.get_field(xmp.exposure_params(1.25), "exposure", 7, "exposure") == pytest.approx(1.25)
    assert xmp.get_field(xmp.crop_params(0.1, 0.2, 0.9, 0.8), "crop", 3, "bottom") == pytest.approx(0.8)


def test_unknown_version_refused():
    with pytest.raises(ValueError, match="no layout"):
        xmp.get_field(xmp.default_params("sigmoid", 3), "sigmoid", 4, "contrast_skewness")
    with pytest.raises(ValueError, match="no layout"):
        xmp.default_params("denoiseprofile", 12)


def test_unknown_field_and_wrong_size_refused():
    b = xmp.default_params("sigmoid", 3)
    with pytest.raises(ValueError, match="no field"):
        xmp.get_field(b, "sigmoid", 3, "nope")
    with pytest.raises(ValueError, match="bytes"):
        xmp.get_field(b + b"\0\0\0\0", "sigmoid", 3, "contrast_skewness")


def test_int_field_refuses_a_float():
    b = xmp.default_params("sigmoid", 3)
    with pytest.raises(ValueError, match="int field"):
        xmp.set_field(b, "sigmoid", 3, "color_processing", 0.5)
    assert xmp.get_field(xmp.set_field(b, "sigmoid", 3, "color_processing", 1), "sigmoid", 3, "color_processing") == 1


def test_default_params_needs_every_default():
    with pytest.raises(ValueError, match="no default"):
        xmp.default_params("crop", 3)
