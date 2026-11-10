"""Independent GLB validation for reconstructed scenes (07 Sections 11.2 and 18).

This parser reads the binary container, glTF JSON, accessors, materials,
textures and embedded images directly. It does not trust trimesh or OpenMVS:
a file that merely exists is not a valid, self-contained scene asset.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import GLB_VALIDATION_FAILED, SceneExportError

GLB_MAGIC = 0x46546C67
GLB_VERSION = 2
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
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
KNOWN_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg"})


@dataclass(frozen=True, slots=True)
class SceneGLBValidation:
    """Facts proven by validating the final scene asset."""

    file_size_bytes: int
    sha256: str
    meshes_count: int
    primitives_count: int
    vertices_count: int
    faces_count: int
    materials_count: int
    textures_count: int
    images_count: int
    has_texture_coordinates: bool
    has_embedded_textures: bool
    extensions_used: tuple[str, ...]
    bounding_box: dict[str, float]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "vertices_count": self.vertices_count,
            "faces_count": self.faces_count,
            "meshes_count": self.meshes_count,
            "primitives_count": self.primitives_count,
            "materials_count": self.materials_count,
            "textures_count": self.textures_count,
            "images_count": self.images_count,
            "has_texture_coordinates": self.has_texture_coordinates,
            "has_embedded_textures": self.has_embedded_textures,
            "extensions_used": list(self.extensions_used),
            "bounding_box": self.bounding_box,
        }


def _invalid(message: str) -> SceneExportError:
    return SceneExportError(GLB_VALIDATION_FAILED, message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_container(data: bytes) -> tuple[dict[str, Any], bytes]:
    if len(data) < 20:
        raise _invalid("The GLB file is too small to contain a header and JSON chunk.")
    magic, version, total_length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise _invalid("The file does not start with the GLB magic header.")
    if version != GLB_VERSION:
        raise _invalid(f"Unsupported GLB container version {version}.")
    if total_length != len(data):
        raise _invalid("The GLB length field does not match the file size.")

    offset = 12
    document: dict[str, Any] | None = None
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
            if document is not None:
                raise _invalid("The GLB contains more than one JSON chunk.")
            try:
                document = json.loads(payload.decode("utf-8").rstrip("\x00 \t\r\n"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _invalid("The GLB JSON chunk is not valid JSON.") from exc
        elif chunk_type == CHUNK_BIN:
            if binary_chunk:
                raise _invalid("The GLB contains more than one BIN chunk.")
            binary_chunk = payload
    if document is None:
        raise _invalid("The GLB has no JSON chunk.")
    if not binary_chunk:
        raise _invalid("The GLB has no BIN chunk; the asset is not self-contained.")
    return document, binary_chunk


def _read_accessor(
    document: dict[str, Any],
    binary_chunk: bytes,
    index: int,
    *,
    expected_type: str | None = None,
    expected_components: frozenset[int] | None = None,
) -> tuple[list[tuple[float, ...]], int]:
    accessors = document.get("accessors") or []
    views = document.get("bufferViews") or []
    if not isinstance(accessors, list) or not 0 <= index < len(accessors):
        raise _invalid("An accessor index is out of range.")
    accessor = accessors[index]
    if not isinstance(accessor, dict):
        raise _invalid("An accessor is not an object.")
    component_type = accessor.get("componentType")
    component_count = TYPE_COMPONENTS.get(str(accessor.get("type")))
    count = accessor.get("count")
    if component_type not in COMPONENT_SIZES or component_count is None:
        raise _invalid("An accessor uses an unknown component or element type.")
    if not isinstance(count, int) or count < 1:
        raise _invalid("An accessor has a non-positive count.")
    if expected_type is not None and accessor.get("type") != expected_type:
        raise _invalid(f"Expected a {expected_type} accessor.")
    if expected_components is not None and component_type not in expected_components:
        raise _invalid("An accessor component type is not accepted here.")

    view_index = accessor.get("bufferView")
    if not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise _invalid("An accessor references a missing bufferView.")
    view = views[view_index]
    if not isinstance(view, dict):
        raise _invalid("A bufferView is not an object.")
    if view.get("buffer") not in (0, None):
        raise _invalid("The GLB references an external buffer.")
    view_offset = int(view.get("byteOffset", 0))
    view_length = int(view.get("byteLength", 0))
    if view_offset < 0 or view_length <= 0 or view_offset + view_length > len(binary_chunk):
        raise _invalid("A bufferView extends past the BIN chunk.")

    element_size = COMPONENT_SIZES[component_type] * component_count
    stride = int(view.get("byteStride", 0)) or element_size
    accessor_offset = int(accessor.get("byteOffset", 0))
    if accessor_offset < 0 or accessor_offset + stride * (count - 1) + element_size > view_length:
        raise _invalid("An accessor extends past its bufferView.")

    prefix = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}[component_type]
    element_format = "<" + prefix * component_count
    start = view_offset + accessor_offset
    values: list[tuple[float, ...]] = []
    for item in range(count):
        unpacked = struct.unpack_from(element_format, binary_chunk, start + item * stride)
        values.append(tuple(float(value) for value in unpacked))
    return values, component_type


def read_glb_document(path: Path) -> tuple[dict[str, Any], bytes]:
    """Return the parsed JSON document and BIN chunk of a GLB file."""
    target = Path(path)
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise _invalid("The GLB file is not readable.") from exc
    return _parse_container(data)


def validate_scene_glb_bytes(data: bytes, *, require_textures: bool = True) -> SceneGLBValidation:
    """Validate an in-memory GLB and return its structural and texture facts."""
    document, binary_chunk = _parse_container(data)

    asset = document.get("asset")
    if not isinstance(asset, dict) or str(asset.get("version")) != "2.0":
        raise _invalid("The glTF asset version is missing or not 2.0.")
    scenes = document.get("scenes")
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    accessors = document.get("accessors")
    buffers = document.get("buffers")
    if not isinstance(scenes, list) or not scenes:
        raise _invalid("The GLB has no scene.")
    if not isinstance(nodes, list) or not nodes:
        raise _invalid("The GLB has no nodes.")
    if not isinstance(meshes, list) or not meshes:
        raise _invalid("The GLB has no mesh.")
    if not isinstance(accessors, list) or not accessors:
        raise _invalid("The GLB has no accessors.")
    if not isinstance(buffers, list) or not buffers:
        raise _invalid("The GLB has no buffer.")
    if buffers[0].get("uri"):
        raise _invalid("The GLB references an external buffer; it is not self-contained.")

    materials = document.get("materials") or []
    textures = document.get("textures") or []
    images = document.get("images") or []
    views = document.get("bufferViews") or []
    if not isinstance(materials, list) or not isinstance(textures, list):
        raise _invalid("The GLB materials or textures are malformed.")
    if not isinstance(images, list) or not isinstance(views, list):
        raise _invalid("The GLB images or bufferViews are malformed.")

    # Textures must be embedded in the BIN chunk, never sidecar files.
    for image_index, image in enumerate(images):
        if not isinstance(image, dict):
            raise _invalid("An image entry is not an object.")
        if image.get("uri"):
            raise _invalid("The GLB references an external image; it is not self-contained.")
        view_index = image.get("bufferView")
        if not isinstance(view_index, int) or not 0 <= view_index < len(views):
            raise _invalid(f"Image {image_index} has no embedded bufferView.")
        mime_type = image.get("mimeType")
        if mime_type not in KNOWN_IMAGE_MIME_TYPES:
            raise _invalid(f"Image {image_index} has an unsupported mime type.")
        length = int(views[view_index].get("byteLength", 0))
        if length <= 0:
            raise _invalid(f"Image {image_index} has an empty bufferView.")

    for texture_index, texture in enumerate(textures):
        if not isinstance(texture, dict):
            raise _invalid("A texture entry is not an object.")
        source = texture.get("source")
        if not isinstance(source, int) or not 0 <= source < len(images):
            raise _invalid(f"Texture {texture_index} references a missing image.")

    lowest = [math.inf, math.inf, math.inf]
    highest = [-math.inf, -math.inf, -math.inf]
    total_vertices = 0
    total_faces = 0
    primitives_count = 0
    has_uv = False
    textured_primitives = 0
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
            positions, _ = _read_accessor(
                document,
                binary_chunk,
                attributes["POSITION"],
                expected_type="VEC3",
                expected_components=frozenset({5126}),
            )
            for position in positions:
                for axis, value in enumerate(position):
                    if not math.isfinite(value):
                        raise _invalid("A mesh contains a non-finite vertex coordinate.")
                    lowest[axis] = min(lowest[axis], value)
                    highest[axis] = max(highest[axis], value)
            total_vertices += len(positions)

            if "TEXCOORD_0" in attributes:
                uvs, _ = _read_accessor(
                    document,
                    binary_chunk,
                    attributes["TEXCOORD_0"],
                    expected_type="VEC2",
                )
                if len(uvs) != len(positions):
                    raise _invalid("TEXCOORD_0 and POSITION accessor counts differ.")
                has_uv = True

            indices = primitive.get("indices")
            if indices is None:
                total_faces += len(positions) // 3
            else:
                values, _ = _read_accessor(
                    document,
                    binary_chunk,
                    indices,
                    expected_type="SCALAR",
                    expected_components=INDEX_COMPONENT_TYPES,
                )
                if len(values) % 3 != 0:
                    raise _invalid("The index accessor count is not a multiple of three.")
                for (value,) in values:
                    if value < 0 or value >= len(positions):
                        raise _invalid("A face index is out of range.")
                total_faces += len(values) // 3

            material_index = primitive.get("material")
            if material_index is not None:
                if not isinstance(material_index, int) or not 0 <= material_index < len(materials):
                    raise _invalid("A primitive references a missing material.")
                material = materials[material_index]
                pbr = material.get("pbrMetallicRoughness") if isinstance(material, dict) else None
                if isinstance(pbr, dict):
                    base_color = pbr.get("baseColorTexture")
                    if isinstance(base_color, dict) and isinstance(base_color.get("index"), int):
                        texture_index = base_color["index"]
                        if not 0 <= texture_index < len(textures):
                            raise _invalid("A material references a missing texture.")
                        textured_primitives += 1

    if total_vertices < 3 or total_faces < 1:
        raise _invalid("The GLB contains no usable polygon geometry.")
    extents = [highest[axis] - lowest[axis] for axis in range(3)]
    if not all(math.isfinite(extent) and extent > 1e-6 for extent in extents):
        raise _invalid("The GLB bounding box is degenerate.")
    if require_textures:
        if not images or not textures:
            raise _invalid("The GLB has no embedded texture images.")
        if not has_uv:
            raise _invalid("The GLB has no TEXCOORD_0 texture coordinates.")
        if textured_primitives == 0 and materials:
            warnings.append("No primitive references a base-colour texture.")
    if materials and textures and textured_primitives == 0 and require_textures:
        raise _invalid("No material references the embedded texture.")

    extensions = document.get("extensionsUsed") or []
    if not isinstance(extensions, list):
        extensions = []

    return SceneGLBValidation(
        file_size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        meshes_count=len(meshes),
        primitives_count=primitives_count,
        vertices_count=total_vertices,
        faces_count=total_faces,
        materials_count=len(materials),
        textures_count=len(textures),
        images_count=len(images),
        has_texture_coordinates=has_uv,
        has_embedded_textures=bool(images) and all(not image.get("uri") for image in images),
        extensions_used=tuple(str(value) for value in extensions),
        bounding_box={
            "width": round(extents[0], 6),
            "height": round(extents[1], 6),
            "depth": round(extents[2], 6),
        },
        warnings=tuple(warnings),
    )


def validate_scene_glb(path: Path, *, require_textures: bool = True) -> SceneGLBValidation:
    """Validate a GLB on disk and verify its checksum is reproducible."""
    target = Path(path)
    if not target.is_file():
        raise _invalid("The exported GLB does not exist.")
    size = target.stat().st_size
    if size <= 0:
        raise _invalid("The exported GLB is empty.")
    data = target.read_bytes()
    result = validate_scene_glb_bytes(data, require_textures=require_textures)
    if result.file_size_bytes != size:
        raise _invalid("The GLB size changed while it was being validated.")
    if result.sha256 != sha256_file(target):
        raise _invalid("The GLB checksum is not reproducible.")
    return result


__all__ = [
    "SceneGLBValidation",
    "read_glb_document",
    "sha256_file",
    "validate_scene_glb",
    "validate_scene_glb_bytes",
]
