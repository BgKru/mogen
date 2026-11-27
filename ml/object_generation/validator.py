"""GLB container, structure and geometry validation.

This validator is deliberately independent of trimesh: it parses the binary
glTF container directly and reads the POSITION/COLOR_0/indices accessors, which
is exactly the evidence required by 06_object_generation.md Section 12 and
09_testing.md Section 12. It rejects a file that merely exists but is not a
usable, self-contained glTF 2.0 binary.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .exceptions import GLB_VALIDATION_FAILED, ExportError

GLB_MAGIC = 0x46546C67  # b"glTF"
GLB_VERSION = 2
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

COMPONENT_SIZES = {
    5120: 1,  # BYTE
    5121: 1,  # UNSIGNED_BYTE
    5122: 2,  # SHORT
    5123: 2,  # UNSIGNED_SHORT
    5125: 4,  # UNSIGNED_INT
    5126: 4,  # FLOAT
}
TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
INDEX_COMPONENT_TYPES = frozenset({5121, 5123, 5125})
COLOR_COMPONENT_TYPES = frozenset({5121, 5123, 5126})


@dataclass(frozen=True, slots=True)
class GLBValidation:
    """Facts proven by a successful validation (09_testing.md Section 12.7)."""

    file_size_bytes: int
    sha256: str
    meshes_count: int
    primitives_count: int
    vertices_count: int
    faces_count: int
    materials_count: int
    textures_count: int
    has_vertex_colors: bool
    bounding_box: dict[str, float]
    is_watertight: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    has_textures: bool = False
    has_uvs: bool = False
    has_normals: bool = False
    has_pbr_materials: bool = False

    def as_metadata(self) -> dict[str, Any]:
        """Return the JSONB-safe result metadata."""
        return {
            "vertices_count": self.vertices_count,
            "faces_count": self.faces_count,
            "meshes_count": self.meshes_count,
            "primitives_count": self.primitives_count,
            "materials_count": self.materials_count,
            "textures_count": self.textures_count,
            "has_vertex_colors": self.has_vertex_colors,
            "has_textures": self.has_textures,
            "has_uvs": self.has_uvs,
            "has_normals": self.has_normals,
            "has_pbr_materials": self.has_pbr_materials,
            "bounding_box": self.bounding_box,
            "warnings": list(self.warnings),
        }


def _invalid(message: str) -> ExportError:
    return ExportError(GLB_VALIDATION_FAILED, message)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_container(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Split a GLB into its JSON document and binary chunk."""
    if len(data) < 20:
        raise _invalid("The GLB file is too small to contain a header and JSON chunk.")
    magic, version, total_length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise _invalid("The file does not start with the GLB magic header.")
    if version != GLB_VERSION:
        raise _invalid(f"Unsupported GLB container version {version}.")
    if total_length != len(data):
        raise _invalid(f"GLB length field {total_length} does not match the file size {len(data)}.")

    offset = 12
    json_document: dict[str, Any] | None = None
    binary_chunk = b""
    while offset < total_length:
        if offset + 8 > total_length:
            raise _invalid("A GLB chunk header extends past the end of the file.")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        if chunk_length % 4 != 0:
            raise _invalid("A GLB chunk length is not 4-byte aligned.")
        if offset + chunk_length > total_length:
            raise _invalid("A GLB chunk extends past the end of the file.")
        payload = data[offset : offset + chunk_length]
        offset += chunk_length

        if chunk_type == CHUNK_JSON:
            if json_document is not None:
                raise _invalid("The GLB contains more than one JSON chunk.")
            try:
                json_document = json.loads(payload.decode("utf-8").rstrip("\x00 \t\r\n"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _invalid("The GLB JSON chunk is not valid JSON.") from exc
        elif chunk_type == CHUNK_BIN:
            if binary_chunk:
                raise _invalid("The GLB contains more than one BIN chunk.")
            binary_chunk = payload
        else:
            # Unknown chunk types are permitted by glTF and must be ignored.
            continue

    if json_document is None:
        raise _invalid("The GLB has no JSON chunk.")
    if not binary_chunk:
        raise _invalid("The GLB has no BIN chunk; the asset is not self-contained.")
    return json_document, binary_chunk


def _read_accessor_values(
    document: dict[str, Any],
    binary_chunk: bytes,
    accessor_index: int,
    *,
    expected_type: str | None = None,
    expected_component_types: frozenset[int] | None = None,
) -> tuple[list[tuple[float, ...]], int]:
    """Read an accessor's values as tuples; returns (values, component_type)."""
    accessors = document.get("accessors") or []
    buffer_views = document.get("bufferViews") or []
    if not isinstance(accessors, list) or not isinstance(buffer_views, list):
        raise _invalid("The GLB accessors or bufferViews are malformed.")
    if accessor_index < 0 or accessor_index >= len(accessors):
        raise _invalid(f"Accessor index {accessor_index} is out of range.")

    accessor = accessors[accessor_index]
    if not isinstance(accessor, dict):
        raise _invalid("An accessor is not an object.")
    component_type = accessor.get("componentType")
    component_count = TYPE_COMPONENTS.get(str(accessor.get("type")))
    count = accessor.get("count")
    if component_type not in COMPONENT_SIZES:
        raise _invalid("An accessor uses an unknown component type.")
    if component_count is None:
        raise _invalid("An accessor uses an unknown element type.")
    if not isinstance(count, int) or count < 1:
        raise _invalid("An accessor has a non-positive count.")
    if expected_type is not None and accessor.get("type") != expected_type:
        raise _invalid(f"Expected a {expected_type} accessor, got {accessor.get('type')!r}.")
    if expected_component_types is not None and component_type not in expected_component_types:
        raise _invalid(f"Accessor component type {component_type} is not accepted here.")

    buffer_view_index = accessor.get("bufferView")
    if not isinstance(buffer_view_index, int) or not 0 <= buffer_view_index < len(buffer_views):
        raise _invalid("An accessor references a missing bufferView.")
    view = buffer_views[buffer_view_index]
    if not isinstance(view, dict):
        raise _invalid("A bufferView is not an object.")
    if view.get("buffer") not in (0, None):
        raise _invalid("The GLB references an external buffer; it is not self-contained.")
    view_offset = int(view.get("byteOffset", 0))
    view_length = int(view.get("byteLength", 0))
    if view_offset < 0 or view_length < 0 or view_offset + view_length > len(binary_chunk):
        raise _invalid("A bufferView extends past the BIN chunk.")

    element_size = COMPONENT_SIZES[component_type] * component_count
    stride = int(view.get("byteStride", 0)) or element_size
    accessor_offset = int(accessor.get("byteOffset", 0))
    if accessor_offset < 0:
        raise _invalid("An accessor has a negative byteOffset.")
    if accessor_offset + stride * (count - 1) + element_size > view_length:
        raise _invalid("An accessor extends past its bufferView.")

    fmt_prefix = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}[component_type]
    element_format = "<" + fmt_prefix * component_count
    absolute_start = view_offset + accessor_offset
    values: list[tuple[float, ...]] = []
    for index in range(count):
        start = absolute_start + index * stride
        unpacked = struct.unpack_from(element_format, binary_chunk, start)
        values.append(tuple(float(value) for value in unpacked))
    return values, component_type


def _accessor_min_max(accessor: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    minimum = accessor.get("min")
    maximum = accessor.get("max")
    if (
        isinstance(minimum, list)
        and isinstance(maximum, list)
        and len(minimum) == len(maximum) == 3
    ):
        return ([float(value) for value in minimum], [float(value) for value in maximum])
    return None


def _accessor_type(
    document: dict[str, Any],
    accessor_index: int,
    *,
    expected_type: str,
    allowed_components: frozenset[int],
) -> int:
    """Validate an accessor's metadata and return its element count."""
    accessors = document.get("accessors") or []
    if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
        raise _invalid(f"Accessor index {accessor_index!r} is out of range.")
    accessor = accessors[accessor_index]
    if not isinstance(accessor, dict):
        raise _invalid("An accessor is not an object.")
    if accessor.get("type") != expected_type:
        raise _invalid(f"Expected a {expected_type} accessor, got {accessor.get('type')!r}.")
    if accessor.get("componentType") not in allowed_components:
        raise _invalid("An accessor uses an unsupported component type.")
    count = accessor.get("count")
    if not isinstance(count, int) or count < 1:
        raise _invalid("An accessor has a non-positive count.")
    return count


def _embedded_texture_image(document: dict[str, Any], texture_index: int | None) -> dict[str, Any]:
    """Return the embedded image of a texture, rejecting external references."""
    textures = document.get("textures") or []
    images = document.get("images") or []
    if not isinstance(texture_index, int) or not 0 <= texture_index < len(textures):
        raise _invalid("A material references a missing texture.")
    texture = textures[texture_index]
    if not isinstance(texture, dict):
        raise _invalid("A texture is not an object.")
    source = texture.get("source")
    if not isinstance(source, int) or not 0 <= source < len(images):
        raise _invalid("A texture references a missing image.")
    image = images[source]
    if not isinstance(image, dict):
        raise _invalid("An image is not an object.")
    if "uri" in image:
        raise _invalid("The GLB references an external image; it is not self-contained.")
    view = image.get("bufferView")
    buffer_views = document.get("bufferViews") or []
    if not isinstance(view, int) or not 0 <= view < len(buffer_views):
        raise _invalid("A texture image has no embedded bufferView.")
    mime = image.get("mimeType")
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise _invalid("A texture image has an unsupported MIME type.")
    return image


def _primitive_material_has_texture(document: dict[str, Any], material_index: int | None) -> bool:
    """Return whether a material carries a valid embedded base-colour texture."""
    materials = document.get("materials") or []
    if not isinstance(material_index, int) or not 0 <= material_index < len(materials):
        return False
    material = materials[material_index]
    if not isinstance(material, dict):
        return False
    pbr = material.get("pbrMetallicRoughness")
    if not isinstance(pbr, dict):
        return False
    base = pbr.get("baseColorTexture")
    if not isinstance(base, dict) or "index" not in base:
        return False
    _embedded_texture_image(document, base.get("index"))
    return True


def _image_payload(document: dict[str, Any], binary_chunk: bytes, image: dict[str, Any]) -> bytes:
    """Return the embedded image bytes and reject corrupt/empty payloads."""
    views = document.get("bufferViews") or []
    index = image.get("bufferView")
    if not isinstance(index, int) or not 0 <= index < len(views):
        raise _invalid("A texture image has no embedded bufferView.")
    view = views[index]
    if not isinstance(view, dict):
        raise _invalid("A bufferView is not an object.")
    offset = int(view.get("byteOffset", 0))
    length = int(view.get("byteLength", 0))
    if offset < 0 or length <= 0 or offset + length > len(binary_chunk):
        raise _invalid("A texture image extends past the BIN chunk.")
    payload = binary_chunk[offset : offset + length]
    if not payload:
        raise _invalid("A texture image is empty.")
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(payload)) as opened:
            width, height = opened.size
    except Exception as exc:
        raise _invalid("A texture image is corrupt or unreadable.") from exc
    if width < 1 or height < 1:
        raise _invalid("A texture image has invalid dimensions.")
    return payload


def _image_dimensions(
    document: dict[str, Any], binary_chunk: bytes, image: dict[str, Any]
) -> tuple[int, int]:
    payload = _image_payload(document, binary_chunk, image)
    with Image.open(io.BytesIO(payload)) as opened:
        return int(opened.width), int(opened.height)


def _validate_texture_slot(
    document: dict[str, Any],
    binary_chunk: bytes,
    slot: Any,
    *,
    slot_name: str,
    attributes: dict[str, Any],
) -> bool:
    """Validate a glTF textureInfo object and its embedded image."""
    if not isinstance(slot, dict):
        raise _invalid(f"{slot_name} is not an object.")
    if slot_name != "baseColorTexture" and slot.get("texCoord", 0) != 0:
        raise _invalid(f"{slot_name} references an unsupported UV set.")
    if "TEXCOORD_0" not in attributes:
        raise _invalid(f"{slot_name} requires TEXCOORD_0 on the primitive.")
    image = _embedded_texture_image(document, slot.get("index"))
    _image_payload(document, binary_chunk, image)
    return True


def _validate_factor(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{name} must be a number.")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise _invalid(f"{name} must be in [0, 1].")
    return number


def _validate_material(
    document: dict[str, Any],
    binary_chunk: bytes,
    material: dict[str, Any],
    attributes: dict[str, Any],
) -> bool:
    """Validate glTF metallic-roughness factors and embedded texture references."""
    pbr = material.get("pbrMetallicRoughness")
    if pbr is None:
        return False
    if not isinstance(pbr, dict):
        raise _invalid("pbrMetallicRoughness is not an object.")
    base = pbr.get("baseColorFactor")
    if base is not None:
        if not isinstance(base, list) or len(base) != 4:
            raise _invalid("baseColorFactor must have four components.")
        for component in base:
            _validate_factor(component, "baseColorFactor")
    if pbr.get("metallicFactor") is not None:
        _validate_factor(pbr["metallicFactor"], "metallicFactor")
    if pbr.get("roughnessFactor") is not None:
        _validate_factor(pbr["roughnessFactor"], "roughnessFactor")
    for slot_name in ("baseColorTexture", "metallicRoughnessTexture"):
        slot = pbr.get(slot_name)
        if slot is not None:
            _validate_texture_slot(
                document,
                binary_chunk,
                slot,
                slot_name=slot_name,
                attributes=attributes,
            )
    for slot_name in ("normalTexture", "occlusionTexture", "emissiveTexture"):
        slot = material.get(slot_name)
        if slot is not None:
            _validate_texture_slot(
                document,
                binary_chunk,
                slot,
                slot_name=slot_name,
                attributes=attributes,
            )
    if material.get("emissiveFactor") is not None:
        emissive = material["emissiveFactor"]
        if not isinstance(emissive, list) or len(emissive) != 3:
            raise _invalid("emissiveFactor must have three components.")
        for component in emissive:
            _validate_factor(component, "emissiveFactor")
    if material.get("normalTexture") is not None:
        pbr_normal = material["normalTexture"]
        if pbr_normal.get("scale") is not None:
            value = pbr_normal["scale"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _invalid("normalTexture.scale must be a number.")
            if not math.isfinite(float(value)):
                raise _invalid("normalTexture.scale must be finite.")
    if material.get("occlusionTexture") is not None:
        pbr_occlusion = material["occlusionTexture"]
        if pbr_occlusion.get("strength") is not None:
            _validate_factor(pbr_occlusion["strength"], "occlusionTexture.strength")
    return True


def validate_glb_bytes(data: bytes) -> GLBValidation:
    """Validate an in-memory GLB and return its structural and geometry facts."""
    document, binary_chunk = _parse_container(data)

    asset = document.get("asset")
    if not isinstance(asset, dict) or str(asset.get("version")) != "2.0":
        raise _invalid("The glTF asset version is missing or not 2.0.")
    scenes = document.get("scenes")
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    accessors = document.get("accessors")
    if not isinstance(scenes, list) or not scenes:
        raise _invalid("The GLB has no scene.")
    if not isinstance(nodes, list) or not nodes:
        raise _invalid("The GLB has no nodes.")
    if not isinstance(meshes, list) or not meshes:
        raise _invalid("The GLB has no mesh.")
    if not isinstance(accessors, list) or not accessors:
        raise _invalid("The GLB has no accessors.")
    if not isinstance(document.get("buffers"), list) or not document["buffers"]:
        raise _invalid("The GLB has no buffer.")
    if document["buffers"][0].get("uri"):
        raise _invalid("The GLB references an external buffer; it is not self-contained.")

    materials = document.get("materials") or []
    textures = document.get("textures") or []
    if not isinstance(materials, list) or not isinstance(textures, list):
        raise _invalid("The GLB materials or textures are malformed.")

    lowest = [math.inf, math.inf, math.inf]
    highest = [-math.inf, -math.inf, -math.inf]
    total_vertices = 0
    total_faces = 0
    primitives_count = 0
    has_vertex_colors = False
    has_textures = False
    has_uvs = False
    has_normals = False
    has_pbr_materials = False
    max_texture_dimension = 0
    warnings: list[str] = []

    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            raise _invalid(f"Mesh {mesh_index} is not an object.")
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise _invalid(f"Mesh {mesh_index} has no primitives.")
        for primitive in primitives:
            primitives_count += 1
            if not isinstance(primitive, dict):
                raise _invalid("A mesh primitive is not an object.")
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise _invalid("A mesh primitive has no POSITION attribute.")
            position_accessor = attributes["POSITION"]
            if not isinstance(position_accessor, int):
                raise _invalid("POSITION must reference an accessor index.")
            positions, _ = _read_accessor_values(
                document,
                binary_chunk,
                position_accessor,
                expected_type="VEC3",
                expected_component_types=frozenset({5126}),
            )
            if not positions:
                raise _invalid("A POSITION accessor is empty.")
            for position in positions:
                for axis, value in enumerate(position):
                    if not math.isfinite(value):
                        raise _invalid("A mesh contains a non-finite vertex coordinate.")
                    lowest[axis] = min(lowest[axis], value)
                    highest[axis] = max(highest[axis], value)
            accessor = accessors[position_accessor]
            declared = _accessor_min_max(accessor)
            if declared is not None:
                for axis in range(3):
                    if declared[0][axis] > declared[1][axis]:
                        raise _invalid("A POSITION accessor declares an inverted bounding box.")
            else:
                warnings.append("POSITION accessor has no min/max; bounds were computed.")
            total_vertices += len(positions)

            if "COLOR_0" in attributes:
                color_accessor = attributes["COLOR_0"]
                if not isinstance(color_accessor, int):
                    raise _invalid("COLOR_0 must reference an accessor index.")
                colors, color_type = _read_accessor_values(
                    document,
                    binary_chunk,
                    color_accessor,
                    expected_component_types=COLOR_COMPONENT_TYPES,
                )
                if color_type not in COLOR_COMPONENT_TYPES:
                    raise _invalid("COLOR_0 uses an unsupported component type.")
                if len(colors) != len(positions):
                    raise _invalid("COLOR_0 and POSITION accessor counts differ.")
                has_vertex_colors = True

            if "TEXCOORD_0" in attributes:
                uv_accessor = attributes["TEXCOORD_0"]
                uv_count = _accessor_type(
                    document,
                    uv_accessor,
                    expected_type="VEC2",
                    allowed_components=frozenset({5126, 5121, 5123}),
                )
                if uv_count != len(positions):
                    raise _invalid("TEXCOORD_0 and POSITION accessor counts differ.")
                uv_values, _ = _read_accessor_values(
                    document,
                    binary_chunk,
                    uv_accessor,
                    expected_type="VEC2",
                )
                coordinates = [value for pair in uv_values for value in pair]
                if not all(math.isfinite(value) for value in coordinates):
                    raise _invalid("TEXCOORD_0 contains non-finite coordinates.")
                if coordinates and (min(coordinates) < -0.01 or max(coordinates) > 1.01):
                    warnings.append("TEXCOORD_0 outside the unit square beyond padding tolerance")
                has_uvs = True

            if "NORMAL" in attributes:
                normal_accessor = attributes["NORMAL"]
                normal_count = _accessor_type(
                    document,
                    normal_accessor,
                    expected_type="VEC3",
                    allowed_components=frozenset({5120, 5122, 5126}),
                )
                if normal_count != len(positions):
                    raise _invalid("NORMAL and POSITION accessor counts differ.")
                normal_values, _ = _read_accessor_values(
                    document,
                    binary_chunk,
                    normal_accessor,
                    expected_type="VEC3",
                )
                for normal in normal_values:
                    if not all(math.isfinite(value) for value in normal):
                        raise _invalid("NORMAL contains non-finite vectors.")
                    if math.sqrt(sum(value * value for value in normal)) <= 1e-9:
                        raise _invalid("NORMAL contains a zero-length vector.")
                has_normals = True

            indices = primitive.get("indices")
            if indices is None:
                total_faces += len(positions) // 3
            else:
                if not isinstance(indices, int):
                    raise _invalid("indices must reference an accessor index.")
                values, _ = _read_accessor_values(
                    document,
                    binary_chunk,
                    indices,
                    expected_type="SCALAR",
                    expected_component_types=INDEX_COMPONENT_TYPES,
                )
                if len(values) % 3 != 0:
                    raise _invalid("The index accessor count is not a multiple of three.")
                position_count = len(positions)
                for (value,) in values:
                    if value < 0 or value >= position_count:
                        raise _invalid("A face index is out of range.")
                total_faces += len(values) // 3

            material_index = primitive.get("material")
            if material_index is not None and (
                not isinstance(material_index, int) or not 0 <= material_index < len(materials)
            ):
                raise _invalid("A primitive references a missing material.")
            if isinstance(material_index, int):
                material = materials[material_index]
                if not isinstance(material, dict):
                    raise _invalid("A material is not an object.")
                if _validate_material(
                    document,
                    binary_chunk,
                    material,
                    attributes,
                ):
                    has_pbr_materials = True
                pbr = material.get("pbrMetallicRoughness")
                base = pbr.get("baseColorTexture") if isinstance(pbr, dict) else None
                if isinstance(base, dict):
                    image = _embedded_texture_image(document, base.get("index"))
                    width, height = _image_dimensions(document, binary_chunk, image)
                    max_texture_dimension = max(max_texture_dimension, width, height)
            if _primitive_material_has_texture(document, material_index):
                has_textures = True

    if has_vertex_colors and not has_normals:
        warnings.append("vertex-colour asset has no NORMAL attribute")
    if has_textures and max_texture_dimension and max_texture_dimension < 256:
        warnings.append(f"base-colour texture is small ({max_texture_dimension}px)")
    if total_faces > 1_000_000:
        warnings.append("asset exceeds 1,000,000 faces")

    if total_vertices < 3 or total_faces < 1:
        raise _invalid("The GLB contains no usable polygon geometry.")
    extents = [highest[axis] - lowest[axis] for axis in range(3)]
    if not all(math.isfinite(extent) and extent > 1e-6 for extent in extents):
        raise _invalid("The GLB bounding box is degenerate.")
    # OBJ-AC-10 requires an appearance; a textured PBR material with embedded
    # imagery is an equally valid appearance for the optical models added by
    # increment 13 (13 Section 5.3). A GLB with neither is still rejected.
    if not has_vertex_colors and not (has_textures and has_uvs):
        raise _invalid(
            "The GLB has neither COLOR_0 vertex colours nor an embedded base-colour "
            "texture with UVs."
        )

    return GLBValidation(
        file_size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        meshes_count=len(meshes),
        primitives_count=primitives_count,
        vertices_count=total_vertices,
        faces_count=total_faces,
        materials_count=len(materials),
        textures_count=len(textures),
        has_vertex_colors=has_vertex_colors,
        bounding_box={
            "width": round(extents[0], 6),
            "height": round(extents[1], 6),
            "depth": round(extents[2], 6),
        },
        warnings=tuple(warnings),
        has_textures=has_textures,
        has_uvs=has_uvs,
        has_normals=has_normals,
        has_pbr_materials=has_pbr_materials,
    )


def validate_glb(path: Path) -> GLBValidation:
    """Validate a GLB on disk and verify the checksum is reproducible."""
    if not path.is_file():
        raise _invalid("The exported GLB does not exist.")
    size = path.stat().st_size
    if size <= 0:
        raise _invalid("The exported GLB is empty.")
    data = path.read_bytes()
    result = validate_glb_bytes(data)
    if result.file_size_bytes != size:
        raise _invalid("The GLB size changed while it was being validated.")
    if result.sha256 != sha256_file(path):
        raise _invalid("The GLB checksum is not reproducible.")
    return result
