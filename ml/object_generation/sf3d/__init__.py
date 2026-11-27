"""Stable Fast 3D adapter for the object worker (increment 13).

The upstream implementation is vendored by pin, not copied: the adapter calls
``SF3D.from_pretrained`` and ``run_image`` through a thin boundary. Only this
package knows the dependency names and the model cache layout, and the heavy
imports are lazy so a TripoSR-only deployment never loads them.
"""

from .adapter import SF3DAdapter
from .loader import SF3DWeights, load_model, verify_weights

__all__ = ["SF3DAdapter", "SF3DWeights", "load_model", "verify_weights"]
