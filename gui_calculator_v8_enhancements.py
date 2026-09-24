import os
import sys
import json
import math
import logging
import tempfile
import threading
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Set, Tuple, Optional, Any, Union

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QTextBrowser, QGroupBox, QSplitter, QScrollArea, QDialog,
    QFileDialog, QHeaderView, QMenu, QTabWidget
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QUrl
from PySide6.QtGui import QFont, QAction, QDesktopServices

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ==================== CROSS-PLATFORM PATH HELPER ====================
def get_user_data_filepath(filename: str = "user_data.json") -> str:
    """Resolves cross-platform config directory."""
    if os.path.exists(filename):
        return filename

    if sys.platform.startswith("win"):
        base_dir = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base_dir = os.path.expanduser("~/Library/Application Support")
    else:
        base_dir = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))

    app_dir = os.path.join(base_dir, "ModMaterialCalculator")
    try:
        os.makedirs(app_dir, exist_ok=True)
        return os.path.join(app_dir, filename)
    except Exception as e:
        logging.error(f"Failed to create directory {app_dir}: {e}")
        return filename


# ==================== WEB SEARCH HELPER ====================
def open_web_search_how_to_obtain(item_id: str) -> None:
    """Constructs a search query and opens default web browser to search how to obtain an item."""
    clean_id = item_id.lstrip("#").replace("_", " ")
    query = f"Minecraft {clean_id} how to obtain"
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.google.com/search?q={encoded_query}"
    QDesktopServices.openUrl(QUrl(url))


# ==================== ADVANCED RECIPE ENGINE ====================
class AdvancedRecipeResolver:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.recipes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.raw_overrides: Set[str] = set()
        self.item_caps: Dict[str, float] = {}  
        self.material_replacements: Dict[str, str] = {}  
        self.preferred_recipes: Dict[str, int] = {}  
        self.owned_inventory: Dict[str, int] = defaultdict(int)  # Inventory / In-Stock items
        self.tag_members: Dict[str, Set[str]] = defaultdict(set)  # Tag membership graph
        self.advancement_triggers: Dict[str, Set[str]] = defaultdict(set)  # Recipe unlock triggers
        self.all_known_items: Set[str] = set()  
        self.namespace_mappings: Dict[str, str] = {}

    def toggle_raw_override(self, item_id: str) -> bool:
        """Toggles treating an item as a base raw material (overriding its crafting step)."""
        norm_id = self.normalize_id(item_id)
        with self._lock:
            if norm_id in self.raw_overrides:
                self.raw_overrides.remove(norm_id)
                return False
            else:
                self.raw_overrides.add(norm_id)
                return True

    def standardize_path(self, path: str) -> str:
        path = path.replace("\\", "_").replace("/", "_")
        path = path.replace("storage_blocks", "block").replace("storage_block", "block")
        path = path.replace("raw_materials", "raw").replace("raw_material", "raw")
        
        parts = path.split("_")
        type_mapping = {
            "ingots": "ingot", "nuggets": "nugget", "blocks": "block", 
            "dusts": "dust", "gears": "gear", "plates": "plate", 
            "gems": "gem", "wires": "wire", "rods": "rod", "ores": "ore",
            "ingot": "ingot", "nugget": "nugget", "block": "block",
            "dust": "dust", "gear": "gear", "plate": "plate",
            "gem": "gem", "wire": "wire", "rod": "rod", "ore": "ore"
        }
        
        types = set(type_mapping.values())
        standardized_parts = [type_mapping.get(p, p) for p in parts]
        
        material_parts = [p for p in standardized_parts if p not in types]
        type_parts = [p for p in standardized_parts if p in types]
        
        if not material_parts or not type_parts:
            return "_".join(standardized_parts)
            
        return "_".join(material_parts + type_parts)

    def normalize_id(self, item_id: Union[str, Dict[str, Any], List[Any]]) -> str:
        if isinstance(item_id, dict):
            if "item" in item_id:
                return self.normalize_id(item_id["item"])
            elif "tag" in item_id:
                return self.normalize_tag(item_id["tag"])
            elif "id" in item_id:
                return self.normalize_id(item_id["id"])
            return ""
        if isinstance(item_id, list) and len(item_id) > 0:
            return self.normalize_id(item_id[0])
        
        s_id = str(item_id).strip()
        if s_id.startswith("#") or s_id.startswith("tag:") or s_id.startswith("c:") or s_id.startswith("forge:"):
            return self.normalize_tag(s_id)

        parts = s_id.split(":", 1)
        if len(parts) == 2:
            ns, path = parts
            path = self.standardize_path(path)
            if ns in self.namespace_mappings:
                ns = self.namespace_mappings[ns]
            s_id = f"{ns}:{path}"
        else:
            s_id = f"minecraft:{self.standardize_path(s_id)}"

        with self._lock:
            self.all_known_items.add(s_id)
        return s_id

    def normalize_tag(self, tag_str: Union[str, Dict[str, Any], List[Any]]) -> str:
        if isinstance(tag_str, dict):
            if "tag" in tag_str:
                return self.normalize_tag(tag_str["tag"])
            elif "item" in tag_str:
                return self.normalize_id(tag_str["item"])
            elif "id" in tag_str:
                return self.normalize_id(tag_str["id"])
            return ""
        if isinstance(tag_str, list) and len(tag_str) > 0:
            return self.normalize_tag(tag_str[0])

        clean_tag = str(tag_str).strip().lstrip("#")
        if clean_tag.startswith("tag:"):
            clean_tag = clean_tag[4:]

        parts = clean_tag.split(":", 1)
        if len(parts) == 2:
            ns, path = parts
            path = self.standardize_path(path)
            if ns in self.namespace_mappings:
                ns = self.namespace_mappings[ns]
            clean_tag = f"{ns}:{path}"
        else:
            clean_tag = f"c:{self.standardize_path(clean_tag)}"

        final_tag = f"#{clean_tag}"
        with self._lock:
            self.all_known_items.add(final_tag)
        return final_tag

    def find_all_item_ids(self, obj: Any) -> None:
        """Recursively inspects JSON structures to extract any mentioned item IDs."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("item", "result", "output", "id", "tag"):
                    if isinstance(v, str):
                        self.normalize_id(v)
                self.find_all_item_ids(v)
        elif isinstance(obj, list):
            for item in obj:
                self.find_all_item_ids(item)
        elif isinstance(obj, str):
            if ":" in obj and not obj.startswith("http") and not obj.endswith(".png") and not obj.endswith(".json"):
                parts = obj.split(":")
                if len(parts) == 2 and parts[0].replace("#", "").isalnum():
                    self.normalize_id(obj)

    def extract_ingredient_ids(self, obj: Any) -> List[str]:
        found = []
        if isinstance(obj, dict):
            if "item" in obj:
                found.append(self.normalize_id(obj["item"]))
            elif "tag" in obj:
                found.append(self.normalize_tag(obj["tag"]))
            elif "id" in obj:
                found.append(self.normalize_id(obj["id"]))
            else:
                for v in obj.values():
                    found.extend(self.extract_ingredient_ids(v))
        elif isinstance(obj, list):
            for item in obj:
                found.extend(self.extract_ingredient_ids(item))
        elif isinstance(obj, str):
            found.append(self.normalize_id(obj))
        return [f for f in found if f]

    def categorize_method(self, recipe_type: Any, file_path: str, tags: List[Any]) -> str:
        r_type = str(recipe_type).lower()
        f_path = str(file_path).replace("\\", "/").lower()
        tag_str = " ".join([str(t).lower() for t in tags])

        if "furnace" in r_type or "smelting" in r_type or "smelting" in f_path or "furnace" in tag_str:
            return "Smelting / Furnace"
        elif "blasting" in r_type or "blasting" in f_path or "blasting" in tag_str:
            return "Blasting / Blast Furnace"
        elif "crushing" in r_type or "pulverizing" in r_type or "grinding" in r_type or "crusher" in f_path:
            return "Crushing / Pulverizing"
        elif "inscriber" in r_type or "inscriber" in f_path:
            return "Inscriber Processing (AE2)"
        elif "transform" in r_type or "transform" in f_path or "charger" in r_type:
            return "In-World / Energy Transformation"
        elif "smithing" in r_type or "smithing" in tag_str:
            return "Smithing Table"
        elif "brewing" in r_type or "brewing" in tag_str:
            return "Brewing Stand"
        else:
            return "Crafting Table"

    def unwrap_recipe_data(self, data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        if not isinstance(data, dict):
            return None, ""
        for key, value in data.items():
            if "recipe" in key and isinstance(value, dict):
                return value, key
        return data, data.get("type", "")

    def parse_tag_file(self, norm_path: str, raw_data: Dict[str, Any]) -> None:
        parts = norm_path.split("/")
        ns = "c"
        if "data" in parts:
            idx = parts.index("data")
            if idx + 1 < len(parts):
                ns = parts[idx + 1]

        tag_subpath = ""
        for tag_folder in ["/tags/item/", "/tags/items/"]:
            if tag_folder in norm_path:
                tag_subpath = norm_path.split(tag_folder)[-1].replace(".json", "")
                break

        if tag_subpath:
            tag_id = self.normalize_tag(f"{ns}:{tag_subpath}")
            values = raw_data.get("values", [])
            for val in values:
                val_id = val.get("id", "") if isinstance(val, dict) else str(val)
                if val_id:
                    norm_val = self.normalize_tag(val_id) if val_id.startswith("#") else self.normalize_id(val_id)
                    with self._lock:
                        self.tag_members[tag_id].add(norm_val)

    def parse_advancement_file(self, raw_data: Dict[str, Any]) -> None:
        rewards = raw_data.get("rewards", {}).get("recipes", [])
        criteria = raw_data.get("criteria", {})
        trigger_items = set()

        for crit in criteria.values():
            conds = crit.get("conditions", {})
            items_list = conds.get("items", [])
            for item_obj in items_list:
                if isinstance(item_obj, dict):
                    for k in ["items", "item", "tag"]:
                        if k in item_obj:
                            val = item_obj[k]
                            if isinstance(val, list):
                                for v in val:
                                    trigger_items.add(self.normalize_id(v))
                            else:
                                trigger_items.add(self.normalize_id(val))

        for recipe_id in rewards:
            norm_recipe = self.normalize_id(recipe_id)
            for trig in trigger_items:
                with self._lock:
                    self.advancement_triggers[norm_recipe].add(trig)

    def parse_json_file(self, file_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            norm_path = file_path.replace("\\", "/")

            if "/tags/item/" in norm_path or "/tags/items/" in norm_path:
                self.parse_tag_file(norm_path, raw_data)
                return

            if "/advancement/" in norm_path or "/advancements/" in norm_path:
                self.parse_advancement_file(raw_data)
                return

            self.find_all_item_ids(raw_data)

            if "/models/item/" in norm_path or "/items/" in norm_path or "/recipes/" in norm_path:
                parts = norm_path.split("/")
                filename = parts[-1].replace(".json", "")
                ns = "minecraft"
                if "assets" in parts:
                    idx = parts.index("assets")
                    if idx + 1 < len(parts):
                        ns = parts[idx + 1]
                elif "data" in parts:
                    idx = parts.index("data")
                    if idx + 1 < len(parts):
                        ns = parts[idx + 1]
                self.normalize_id(f"{ns}:{filename}")

            data, recipe_type = self.unwrap_recipe_data(raw_data)
            if not data:
                return

            tags = data.get("tags", [])
            method = self.categorize_method(recipe_type, file_path, tags)
            
            result_id = None
            result_count = 1

            if "result" in data:
                res = data["result"]
                if isinstance(res, str):
                    result_id = self.normalize_id(res)
                elif isinstance(res, dict):
                    result_id = self.normalize_id(res)
                    result_count = res.get("count", res.get("components", {}).get("count", 1))
            elif "output" in data:
                res = data["output"]
                result_id = self.normalize_id(res)
                if isinstance(res, dict):
                    result_count = res.get("count", 1)
            elif "description" in data and "identifier" in data["description"]:
                result_id = self.normalize_id(data["description"]["identifier"])

            if not result_id:
                return

            inputs = defaultdict(int)

            if "pattern" in data and "key" in data:
                key_map = data["key"]
                pattern = data["pattern"]
                for row in pattern:
                    for char in row:
                        if char != " " and char in key_map:
                            for ing in self.extract_ingredient_ids(key_map[char]):
                                inputs[ing] += 1
                                break
            elif "ae2:inscriber" in str(recipe_type) or "inscriber" in file_path:
                for key in ["top", "middle", "bottom", "ingredients"]:
                    if key in data:
                        for ing in self.extract_ingredient_ids(data[key]):
                            inputs[ing] += 1
            elif "ae2:transform" in str(recipe_type) or "transform" in file_path:
                for key in ["ingredients", "from"]:
                    if key in data:
                        for ing in self.extract_ingredient_ids(data[key]):
                            inputs[ing] += 1
            elif "ingredients" in data:
                for ing in data["ingredients"]:
                    for item_id in self.extract_ingredient_ids(ing):
                        inputs[item_id] += 1
                        break
            elif "ingredient" in data:
                for item_id in self.extract_ingredient_ids(data["ingredient"]):
                    inputs[item_id] += 1
                    break

            if inputs and result_id:
                new_recipe = {
                    "count": result_count,
                    "inputs": dict(inputs),
                    "method": method
                }
                with self._lock:
                    if not any(
                        r["count"] == new_recipe["count"] and
                        r["method"] == new_recipe["method"] and
                        r["inputs"] == new_recipe["inputs"]
                        for r in self.recipes[result_id]
                    ):
                        self.recipes[result_id].append(new_recipe)

        except Exception as e:
            logging.debug(f"Could not parse JSON file '{file_path}': {e}")

    def scan_repositories(self, repo_paths: List[str]) -> None:
        with self._lock:
            self.recipes.clear()
            self.all_known_items.clear()
            self.tag_members.clear()
            self.advancement_triggers.clear()

        json_files = []
        for repo in repo_paths:
            if not os.path.exists(repo):
                continue
            for root, _, files in os.walk(repo):
                for file in files:
                    if file.endswith(".json"):
                        json_files.append(os.path.join(root, file))

        with ThreadPoolExecutor() as executor:
            executor.map(self.parse_json_file, json_files)

    def is_self_referential(self, item_id: str) -> bool:
        norm_id = self.normalize_id(item_id)
        recipes = self.recipes.get(norm_id, [])
        for r in recipes:
            if any(self.normalize_id(inp) == norm_id for inp in r.get("inputs", {})):
                return True
        return False

    def is_uncrafting_cycle(self, item_id: str, recipe: Dict[str, Any], inventory_tracker: Dict[str, int]) -> bool:
        total_input_count = sum(recipe.get("inputs", {}).values())
        yield_count = recipe.get("count", 1)

        if yield_count > total_input_count:
            for inp_id in recipe.get("inputs", {}):
                norm_inp = self.normalize_id(inp_id)
                if inventory_tracker.get(norm_inp, 0) > 0:
                    continue

                for b_recipe in self.recipes.get(norm_inp, []):
                    if any(self.normalize_id(b_inp) == item_id for b_inp in b_recipe.get("inputs", {})):
                        return True
        return False

    def get_tag_members_recursive(self, tag_id: str, visited: Optional[Set[str]] = None) -> Set[str]:
        if visited is None:
            visited = set()
        norm_tag = self.normalize_tag(tag_id)
        if norm_tag in visited:
            return set()
        visited.add(norm_tag)

        concrete_items = set()
        with self._lock:
            raw_members = self.tag_members.get(norm_tag, set()).copy()

        for member in raw_members:
            if member.startswith("#"):
                concrete_items.update(self.get_tag_members_recursive(member, visited.copy()))
            else:
                concrete_items.add(member)
        return concrete_items

    def get_matching_tags_for_item(self, item_id: str) -> List[str]:
        norm_item = self.normalize_id(item_id)
        item_stem = norm_item.split(":")[-1] if ":" in norm_item else norm_item
        matching = []
        with self._lock:
            all_tags = list(self.tag_members.keys())

        for tag in all_tags:
            members = self.get_tag_members_recursive(tag)
            if norm_item in members or any(item_stem in m for m in members):
                matching.append(tag)

        if not matching:
            with self._lock:
                for tag in self.all_known_items:
                    if tag.startswith("#"):
                        tag_stem = tag.split(":")[-1] if ":" in tag else tag
                        if item_stem in tag_stem or tag_stem in item_stem:
                            matching.append(tag)

        return sorted(list(set(matching)))

    def get_items_matching_tag(self, tag_id: str) -> List[str]:
        norm_tag = self.normalize_tag(tag_id)
        resolved_members = self.get_tag_members_recursive(norm_tag)
        if resolved_members:
            return sorted(list(resolved_members))

        tag_stem = norm_tag.lstrip("#").split(":")[-1] if ":" in norm_tag else norm_tag.lstrip("#")
        matches = []
        with self._lock:
            for item in self.all_known_items:
                if not item.startswith("#"):
                    item_stem = item.split(":")[-1] if ":" in item else item
                    if tag_stem in item_stem:
                        matches.append(item)
        return sorted(list(set(matches)))

    def _deduct_available_inventory(self, item_id: str, needed_qty: int, inventory_tracker: Dict[str, int]) -> Tuple[int, int]:
        if needed_qty <= 0:
            return 0, 0

        used_stock = 0
        rem_needed = needed_qty

        if item_id in inventory_tracker and inventory_tracker[item_id] > 0:
            avail = inventory_tracker[item_id]
            used = min(rem_needed, avail)
            inventory_tracker[item_id] -= used
            used_stock += used
            rem_needed -= used

        if rem_needed > 0 and item_id.startswith("#"):
            matching_items = self.get_items_matching_tag(item_id)
            for m_item in matching_items:
                if rem_needed <= 0:
                    break
                if m_item in inventory_tracker and inventory_tracker[m_item] > 0:
                    avail = inventory_tracker[m_item]
                    used = min(rem_needed, avail)
                    inventory_tracker[m_item] -= used
                    used_stock += used
                    rem_needed -= used

        return rem_needed, used_stock

    def get_raw_materials(
        self,
        item_id: str,
        target_amount: float = 1.0,
        visited: Optional[Set[str]] = None,
        item_usage_tracker: Optional[Dict[str, float]] = None,
        inventory_tracker: Optional[Dict[str, int]] = None,
        depth: int = 0
    ) -> Tuple[Dict[str, float], Dict[str, Dict[str, Any]]]:
        if depth > 50:
            logging.warning(f"Maximum recursion depth reached for item '{item_id}'.")
            return {item_id: int(math.ceil(target_amount))}, {}

        item_id = self.normalize_id(item_id)
        target_amount = int(math.ceil(target_amount))
        
        if item_id in self.material_replacements:
            item_id = self.material_replacements[item_id]

        if visited is None:
            visited = set()
        if item_usage_tracker is None:
            item_usage_tracker = defaultdict(float)
        if inventory_tracker is None:
            with self._lock:
                inventory_tracker = defaultdict(int, self.owned_inventory.copy())

        eff_target_amount, used_from_inv = self._deduct_available_inventory(item_id, target_amount, inventory_tracker)

        raw_totals: Dict[str, float] = defaultdict(float)
        method_steps: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(lambda: {
            "amount": 0,
            "inputs": defaultdict(float)
        }))

        if eff_target_amount <= 0:
            return dict(raw_totals), method_steps

        cap = self.item_caps.get(item_id, None)
        if cap is None and item_id in self.recipes:
            for r in self.recipes[item_id]:
                if any(self.normalize_id(inp) == item_id for inp in r["inputs"]):
                    cap = 1.0
                    break

        if cap is not None:
            already_used = item_usage_tracker[item_id]
            remaining_allowance = max(0.0, cap - already_used)
            eff_target_amount = min(eff_target_amount, remaining_allowance)

        eff_target_amount = int(math.ceil(eff_target_amount))

        if eff_target_amount <= 0:
            return dict(raw_totals), method_steps

        if item_id in self.raw_overrides or item_id.startswith("#") or item_id not in self.recipes or item_id in visited:
            raw_totals[item_id] += eff_target_amount
            return dict(raw_totals), method_steps

        candidate_recipes = self.recipes[item_id]
        chosen_recipe = None

        if item_id in self.preferred_recipes:
            pref_idx = self.preferred_recipes[item_id]
            if 0 <= pref_idx < len(candidate_recipes):
                r = candidate_recipes[pref_idx]
                inputs_in_visited = any(self.normalize_id(inp) in visited for inp in r["inputs"] if self.normalize_id(inp) != item_id)
                uncrafting_loop = self.is_uncrafting_cycle(item_id, r, inventory_tracker)
                if not inputs_in_visited and not uncrafting_loop:
                    chosen_recipe = r

        if not chosen_recipe:
            for r in candidate_recipes:
                inputs_in_visited = any(self.normalize_id(inp) in visited for inp in r["inputs"] if self.normalize_id(inp) != item_id)
                uncrafting_loop = self.is_uncrafting_cycle(item_id, r, inventory_tracker)
                if not inputs_in_visited and not uncrafting_loop:
                    chosen_recipe = r
                    break

        if not chosen_recipe:
            for r in candidate_recipes:
                if not any(self.normalize_id(inp) in visited for inp in r["inputs"]):
                    if not self.is_uncrafting_cycle(item_id, r, inventory_tracker):
                        chosen_recipe = r
                        break

        if not chosen_recipe:
            raw_totals[item_id] += eff_target_amount
            return dict(raw_totals), method_steps

        visited.add(item_id)
        item_usage_tracker[item_id] += eff_target_amount

        recipe = chosen_recipe
        craft_yield = recipe["count"] if recipe["count"] > 0 else 1
        
        crafts_needed = int(math.ceil(eff_target_amount / craft_yield))
        method = recipe["method"]

        method_steps[method][item_id]["amount"] += eff_target_amount

        for input_id, req_qty in recipe["inputs"].items():
            norm_input_id = self.normalize_id(input_id)
            raw_req = req_qty * crafts_needed
            
            inp_cap = self.item_caps.get(norm_input_id, None)
            if inp_cap is None and norm_input_id in self.recipes:
                for r in self.recipes[norm_input_id]:
                    if any(self.normalize_id(inp) == norm_input_id for inp in r["inputs"]):
                        inp_cap = 1.0
                        break

            eff_req = raw_req
            if inp_cap is not None:
                already_used_input = item_usage_tracker[norm_input_id]
                rem_allowance = max(0.0, inp_cap - already_used_input)
                eff_req = min(raw_req, rem_allowance)

            eff_req = int(math.ceil(eff_req))

            if eff_req > 0:
                method_steps[method][item_id]["inputs"][norm_input_id] += eff_req

                sub_raw, sub_methods = self.get_raw_materials(
                    norm_input_id, eff_req, visited.copy(), item_usage_tracker, inventory_tracker, depth + 1
                )
                for r_id, r_qty in sub_raw.items():
                    raw_totals[r_id] += r_qty
                for m_type, items in sub_methods.items():
                    for sub_item, sub_data in items.items():
                        method_steps[m_type][sub_item]["amount"] += sub_data["amount"]
                        for p_inp, p_qty in sub_data["inputs"].items():
                            method_steps[m_type][sub_item]["inputs"][p_inp] += p_qty

        return dict(raw_totals), method_steps


# ==================== QT THREAD SIGNALS ====================
class WorkerSignals(QObject):
    rescan_done = Signal()
    calc_done = Signal(dict, dict)


# ==================== ENHANCED TAG INSPECTOR DIALOG ====================
class TagInspectorDialog(QDialog):
    def __init__(self, parent: QWidget, resolver: AdvancedRecipeResolver, tag_id: str, callback: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Tag Inspector: {tag_id}")
        self.resize(560, 480)
        self.resolver = resolver
        self.tag_id = tag_id
        self.callback = callback

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Tag Identifier:</b> {tag_id}"))

        self.override_banner = QLabel()
        layout.addWidget(self.override_banner)

        layout.addWidget(QLabel("<b>Known Matching Items for this Tag (Double-Click or Select to Use):</b>"))
        self.item_list = QListWidget()
        self.item_list.itemDoubleClicked.connect(self.use_selected_item)
        layout.addWidget(self.item_list)

        self.populate_items()

        btn_layout = QHBoxLayout()
        self.use_btn = QPushButton("★ Use Selected Item for Tag")
        self.use_btn.clicked.connect(self.use_selected_item)
        btn_layout.addWidget(self.use_btn)

        self.clear_btn = QPushButton("Clear Tag Substitution")
        self.clear_btn.clicked.connect(self.clear_override)
        btn_layout.addWidget(self.clear_btn)

        web_btn = QPushButton("🌐 Search 'How to Obtain'")
        web_btn.clicked.connect(lambda: open_web_search_how_to_obtain(self.tag_id))
        btn_layout.addWidget(web_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.update_override_banner()

    def update_override_banner(self) -> None:
        current_target = self.resolver.material_replacements.get(self.tag_id)
        if current_target:
            self.override_banner.setText(f"🏷️ <b>Active Item Substitution:</b> Using <font color='#ffffff'><b>{current_target}</b></font> in place of {self.tag_id}")
            self.override_banner.setStyleSheet("background-color: #27ae60; color: white; padding: 6px; border-radius: 4px;")
            self.clear_btn.setEnabled(True)
        else:
            self.override_banner.setText("<i>No item substitution active for this tag (uses generic tag requirements).</i>")
            self.override_banner.setStyleSheet("color: #7f8c8d; padding: 2px;")
            self.clear_btn.setEnabled(False)

    def populate_items(self) -> None:
        self.item_list.clear()
        matching_items = self.resolver.get_items_matching_tag(self.tag_id)
        current_target = self.resolver.material_replacements.get(self.tag_id)

        if matching_items:
            for item in matching_items:
                label_text = f"{item}  [ ★ Currently Active ]" if item == current_target else item
                item_widget = QListWidgetItem(label_text)
                item_widget.setData(Qt.UserRole, item)
                if item == current_target:
                    item_widget.setFont(QFont("Helvetica", 10, QFont.Bold))
                self.item_list.addItem(item_widget)
        else:
            self.item_list.addItem("[ No direct item mappings found in loaded repos ]")

    def use_selected_item(self) -> None:
        items = self.item_list.selectedItems()
        if not items:
            return
        selected_item_id = items[0].data(Qt.UserRole)
        if not selected_item_id or selected_item_id.startswith("["):
            return

        self.resolver.material_replacements[self.tag_id] = selected_item_id
        self.update_override_banner()
        self.populate_items()
        if self.callback:
            self.callback()

    def clear_override(self) -> None:
        if self.tag_id in self.resolver.material_replacements:
            del self.resolver.material_replacements[self.tag_id]
            self.update_override_banner()
            self.populate_items()
            if self.callback:
                self.callback()


# ==================== ENHANCED ITEM INSPECTOR DIALOG ====================
class ItemInspectorDialog(QDialog):
    def __init__(self, parent: QWidget, resolver: AdvancedRecipeResolver, item_id: str, callback: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Item Inspector: {item_id}")
        self.resize(700, 620)
        self.resolver = resolver
        self.item_id = item_id
        self.callback = callback

        layout = QVBoxLayout(self)

        recipes = self.resolver.recipes.get(self.item_id, [])
        recipe_count = len(recipes)
        header_text = f"Item Details & Recipe Series:\n{item_id}"
        header = QLabel(header_text)
        header.setFont(QFont("Helvetica", 11, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # Self-Referential Origin Alert Banner
        if self.resolver.is_self_referential(self.item_id):
            origin_box = QWidget()
            origin_layout = QHBoxLayout(origin_box)
            origin_layout.setContentsMargins(8, 6, 8, 6)

            alert_text = QLabel("⚠️ <b>Origin Unknown:</b> Item requires itself as a crafting ingredient. Initial origin must be acquired externally.")
            alert_text.setStyleSheet("color: white;")
            alert_text.setWordWrap(True)
            origin_layout.addWidget(alert_text, stretch=1)

            search_origin_btn = QPushButton("🌐 How to Obtain?")
            search_origin_btn.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; padding: 4px 10px;")
            search_origin_btn.clicked.connect(lambda: open_web_search_how_to_obtain(self.item_id))
            origin_layout.addWidget(search_origin_btn)

            origin_box.setStyleSheet("background-color: #c0392b; border-radius: 4px;")
            layout.addWidget(origin_box)

        if recipe_count > 1:
            alert = QLabel(f"⚡ <b>Multiple Crafting Recipes Found!</b> ({recipe_count} options available below)")
            alert.setStyleSheet("background-color: #f39c12; color: white; padding: 6px; border-radius: 4px;")
            alert.setAlignment(Qt.AlignCenter)
            layout.addWidget(alert)

        # Advancement Unlock Triggers
        adv_trigs = self.resolver.advancement_triggers.get(self.item_id, set())
        if adv_trigs:
            trig_str = ", ".join(list(adv_trigs)[:5])
            layout.addWidget(QLabel(f"🔑 <b>Recipe Unlocked By Trigger:</b> <font color='#27ae60'>{trig_str}</font>"))

        matching_tags = self.resolver.get_matching_tags_for_item(item_id)
        if matching_tags:
            tag_str = ", ".join(matching_tags[:6])
            if len(matching_tags) > 6:
                tag_str += f" (+{len(matching_tags) - 6} more)"
            layout.addWidget(QLabel(f"<b>Associated Tags:</b> <font color='#3498db'>{tag_str}</font>"))

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.recipe_tab = QWidget()
        self.setup_recipe_tab()
        self.tabs.addTab(self.recipe_tab, f"Crafting Recipes ({recipe_count})")

        self.series_tab = QWidget()
        self.setup_series_tab()
        self.tabs.addTab(self.series_tab, "Pattern Series (Ingredient Tree)")

        self.raw_tab = QWidget()
        self.setup_raw_tab()
        self.tabs.addTab(self.raw_tab, "Item Raw Materials")

        btn_layout = QHBoxLayout()

        self.override_btn = QPushButton()
        self.update_override_btn_state()
        self.override_btn.clicked.connect(self.toggle_override)
        btn_layout.addWidget(self.override_btn)

        clear_pref_btn = QPushButton("Clear Recipe Preference")
        clear_pref_btn.clicked.connect(self.clear_preference)
        btn_layout.addWidget(clear_pref_btn)

        web_search_btn = QPushButton("🌐 Search 'How to Obtain'")
        web_search_btn.clicked.connect(lambda: open_web_search_how_to_obtain(self.item_id))
        btn_layout.addWidget(web_search_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def update_override_btn_state(self) -> None:
        if self.item_id in self.resolver.raw_overrides:
            self.override_btn.setText("🛠️ Restore Crafting (Remove Override)")
            self.override_btn.setStyleSheet("background-color: #27ae60; color: white;")
        else:
            self.override_btn.setText("🛑 Override Step (Treat as Raw Material)")
            self.override_btn.setStyleSheet("background-color: #c0392b; color: white;")

    def toggle_override(self) -> None:
        self.resolver.toggle_raw_override(self.item_id)
        self.update_override_btn_state()
        self.populate_recipes()
        self.populate_series_tree()
        self.populate_raw_tab()
        if self.callback:
            self.callback()

    def setup_recipe_tab(self) -> None:
        t_layout = QVBoxLayout(self.recipe_tab)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        t_layout.addWidget(self.scroll)
        self.populate_recipes()

    def populate_recipes(self) -> None:
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        recipes = self.resolver.recipes.get(self.item_id, [])
        current_pref = self.resolver.preferred_recipes.get(self.item_id, None)
        norm_self = self.resolver.normalize_id(self.item_id)

        if not recipes:
            no_recipe = QLabel("No recipe is defined for this item in loaded repositories.\n\nIt is likely a base raw material, common tag, or dropped item.")
            no_recipe.setWordWrap(True)
            self.scroll_layout.addWidget(no_recipe)
            return

        for i, recipe in enumerate(recipes):
            is_active = (current_pref == i)
            title = f"Recipe Option {i+1}"
            if is_active:
                title += "  [ ★ Preferred Active ]"
            elif current_pref is None and i == 0:
                title += "  [ Default Active ]"

            box = QGroupBox(title)
            box_layout = QVBoxLayout(box)

            box_layout.addWidget(QLabel(f"<b>Method:</b> {recipe['method']}"))
            box_layout.addWidget(QLabel(f"<b>Yields:</b> {recipe['count']}x"))
            box_layout.addWidget(QLabel("<b>Ingredients Required:</b>"))
            for ing_id, ing_qty in recipe['inputs'].items():
                norm_ing = self.resolver.normalize_id(ing_id)
                if norm_ing == norm_self:
                    box_layout.addWidget(QLabel(f"  • {ing_qty} x {ing_id} <font color='#e74c3c'><b>(⚠️ Self-Referential — Origin Unknown)</b></font>"))
                else:
                    box_layout.addWidget(QLabel(f"  • {ing_qty} x {ing_id}"))

            btn_hbox = QHBoxLayout()
            btn_hbox.addStretch()

            select_btn = QPushButton("★ Active Preference" if is_active else "Select as Preferred Recipe")
            select_btn.setEnabled(not is_active)
            select_btn.clicked.connect(lambda checked, idx=i: self.set_preferred_recipe(idx))
            btn_hbox.addWidget(select_btn)

            box_layout.addLayout(btn_hbox)
            self.scroll_layout.addWidget(box)

        self.scroll_layout.addStretch()

    def set_preferred_recipe(self, idx: int) -> None:
        self.resolver.preferred_recipes[self.item_id] = idx
        self.populate_recipes()
        self.populate_series_tree()
        self.populate_raw_tab()
        if self.callback:
            self.callback()

    def clear_preference(self) -> None:
        if self.item_id in self.resolver.preferred_recipes:
            del self.resolver.preferred_recipes[self.item_id]
            self.populate_recipes()
            self.populate_series_tree()
            self.populate_raw_tab()
            if self.callback:
                self.callback()

    def setup_series_tab(self) -> None:
        s_layout = QVBoxLayout(self.series_tab)
        s_layout.addWidget(QLabel("Recursive Crafting Dependency Series:"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item / Component ID", "Quantity Needed", "Crafting Method"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        s_layout.addWidget(self.tree)
        self.populate_series_tree()

    def populate_series_tree(self) -> None:
        self.tree.clear()
        root_item = QTreeWidgetItem([self.item_id, "1", "Target Output"])
        self.tree.addTopLevelItem(root_item)
        self._build_tree_recursive(root_item, self.item_id, 1, set(), 0)
        self.tree.expandAll()

    def _build_tree_recursive(self, parent_node: QTreeWidgetItem, item_id: str, target_qty: int, visited: Set[str], depth: int) -> None:
        if depth > 15 or item_id in visited or item_id.startswith("#") or item_id not in self.resolver.recipes:
            return

        visited.add(item_id)
        candidate_recipes = self.resolver.recipes[item_id]
        pref_idx = self.resolver.preferred_recipes.get(item_id, 0)
        recipe = candidate_recipes[pref_idx] if 0 <= pref_idx < len(candidate_recipes) else candidate_recipes[0]

        craft_yield = recipe["count"] if recipe["count"] > 0 else 1
        crafts_needed = int(math.ceil(target_qty / craft_yield))

        for ing_id, req_qty in recipe["inputs"].items():
            norm_ing = self.resolver.normalize_id(ing_id)
            total_req = req_qty * crafts_needed
            method = recipe["method"]
            child_node = QTreeWidgetItem([norm_ing, str(total_req), method])
            parent_node.addChild(child_node)
            self._build_tree_recursive(child_node, norm_ing, total_req, visited.copy(), depth + 1)

    def setup_raw_tab(self) -> None:
        r_layout = QVBoxLayout(self.raw_tab)
        r_layout.addWidget(QLabel("Isolated Raw Material Requirements for 1x Output:"))
        self.raw_tree = QTreeWidget()
        self.raw_tree.setHeaderLabels(["Category", "Namespace", "Material Name", "Quantity Needed", "Stacks"])
        self.raw_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.raw_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.raw_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.raw_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.raw_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        r_layout.addWidget(self.raw_tree)
        self.populate_raw_tab()

    def populate_raw_tab(self) -> None:
        self.raw_tree.clear()
        raw_mats, _ = self.resolver.get_raw_materials(self.item_id, target_amount=1)
        for mat, amt in sorted(raw_mats.items(), key=lambda x: x[1], reverse=True):
            amt_int = int(math.ceil(amt))
            stacks = amt_int // 64
            rem_items = amt_int % 64
            stack_str = f"{stacks} stacks + {rem_items}" if stacks >= 1 else "-"

            is_tag = mat.startswith("#")
            cat_str = "Tag" if is_tag else "Item"
            clean_mat = mat.lstrip("#")
            ns, name = clean_mat.split(":", 1) if ":" in clean_mat else ("minecraft", clean_mat)

            self.raw_tree.addTopLevelItem(QTreeWidgetItem([cat_str, ns, name, str(amt_int), stack_str]))


# ==================== MANAGERIAL DIALOGS ====================
class RecipePreferenceManagerDialog(QDialog):
    def __init__(self, parent: QWidget, resolver: AdvancedRecipeResolver, callback: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Preferred Crafting Recipes")
        self.resize(620, 420)
        self.resolver = resolver
        self.callback = callback

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Active User Recipe Preferences:"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item ID", "Preferred Option", "Method", "Yields & Inputs"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.tree)

        self.refresh_tree()

        btn_layout = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected Preference")
        remove_btn.clicked.connect(self.remove_preference)
        btn_layout.addWidget(remove_btn)

        clear_all_btn = QPushButton("Clear All Recipe Preferences")
        clear_all_btn.clicked.connect(self.clear_all_preferences)
        btn_layout.addWidget(clear_all_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def refresh_tree(self) -> None:
        self.tree.clear()
        for item_id, pref_idx in list(self.resolver.preferred_recipes.items()):
            recipes = self.resolver.recipes.get(item_id, [])
            if 0 <= pref_idx < len(recipes):
                r = recipes[pref_idx]
                inputs_str = ", ".join([f"{q}x {ing}" for ing, q in r["inputs"].items()])
                tree_item = QTreeWidgetItem([item_id, f"Option {pref_idx + 1}", r["method"], f"{r['count']}x ({inputs_str})"])
            else:
                tree_item = QTreeWidgetItem([item_id, f"Option {pref_idx + 1}", "Unknown", "Invalid Index"])
            self.tree.addTopLevelItem(tree_item)

    def remove_preference(self) -> None:
        selected = self.tree.selectedItems()
        if selected:
            item_id = selected[0].text(0)
            if item_id in self.resolver.preferred_recipes:
                del self.resolver.preferred_recipes[item_id]
                self.refresh_tree()
                if self.callback:
                    self.callback()

    def clear_all_preferences(self) -> None:
        if self.resolver.preferred_recipes:
            self.resolver.preferred_recipes.clear()
            self.refresh_tree()
            if self.callback:
                self.callback()


class MaterialReplacementDialog(QDialog):
    def __init__(self, parent: QWidget, resolver: AdvancedRecipeResolver, target_item: str, callback: Any) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Replace Material: {target_item}")
        self.resize(500, 420)
        self.resolver = resolver
        self.target_item = target_item
        self.callback = callback

        layout = QVBoxLayout(self)

        label = QLabel(f"Replace '{target_item}' with:")
        label.setFont(QFont("Helvetica", 10, QFont.Bold))
        layout.addWidget(label)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Filter known items/tags...")
        self.search_entry.textChanged.connect(self.filter_items)
        search_layout.addWidget(self.search_entry)
        layout.addLayout(search_layout)

        self.item_listwidget = QListWidget()
        self.item_listwidget.itemSelectionChanged.connect(self.on_select)
        layout.addWidget(self.item_listwidget)

        self.filter_items()

        entry_layout = QHBoxLayout()
        entry_layout.addWidget(QLabel("Selected/Custom:"))
        self.selection_entry = QLineEdit()
        entry_layout.addWidget(self.selection_entry)
        layout.addLayout(entry_layout)

        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("Clear Override")
        clear_btn.clicked.connect(self.clear_override)
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply Replacement")
        apply_btn.clicked.connect(self.apply_replacement)
        btn_layout.addWidget(apply_btn)

        layout.addLayout(btn_layout)

        if target_item in self.resolver.material_replacements:
            self.selection_entry.setText(self.resolver.material_replacements[target_item])

    def filter_items(self) -> None:
        query = self.search_entry.text().lower().strip()
        self.item_listwidget.clear()
        for item in sorted(list(self.resolver.all_known_items)):
            if not query or query in item.lower():
                self.item_listwidget.addItem(item)

    def on_select(self) -> None:
        items = self.item_listwidget.selectedItems()
        if items:
            self.selection_entry.setText(items[0].text())

    def apply_replacement(self) -> None:
        new_val = self.selection_entry.text().strip()
        if new_val:
            self.resolver.material_replacements[self.target_item] = new_val
        self.callback()
        self.accept()

    def clear_override(self) -> None:
        if self.target_item in self.resolver.material_replacements:
            del self.resolver.material_replacements[self.target_item]
        self.callback()
        self.accept()


class MaterialReplacementManagerDialog(QDialog):
    def __init__(self, parent: QWidget, resolver: AdvancedRecipeResolver) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Material Replacements & Overrides")
        self.resize(580, 420)
        self.resolver = resolver

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Active Material Replacements & Custom Overrides:"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Original Material / Tag", "Replacement Material"])
        self.tree.header().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.tree)

        self.refresh_tree()

        entry_layout = QHBoxLayout()
        entry_layout.addWidget(QLabel("Original:"))
        self.src_entry = QLineEdit()
        entry_layout.addWidget(self.src_entry)

        entry_layout.addWidget(QLabel("Replace With:"))
        self.tgt_entry = QLineEdit()
        entry_layout.addWidget(self.tgt_entry)

        add_btn = QPushButton("Add/Update Override")
        add_btn.clicked.connect(self.add_override)
        entry_layout.addWidget(add_btn)

        layout.addLayout(entry_layout)

        btn_layout = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected Override")
        remove_btn.clicked.connect(self.remove_override)
        btn_layout.addWidget(remove_btn)

        clear_all_btn = QPushButton("Clear All Overrides")
        clear_all_btn.clicked.connect(self.clear_all_overrides)
        btn_layout.addWidget(clear_all_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def refresh_tree(self) -> None:
        self.tree.clear()
        for k, v in self.resolver.material_replacements.items():
            self.tree.addTopLevelItem(QTreeWidgetItem([k, v]))

    def add_override(self) -> None:
        src = self.src_entry.text().strip()
        tgt = self.tgt_entry.text().strip()
        if src and tgt:
            self.resolver.material_replacements[src] = tgt
            self.refresh_tree()
            self.src_entry.clear()
            self.tgt_entry.clear()

    def remove_override(self) -> None:
        selected = self.tree.selectedItems()
        if selected:
            src = selected[0].text(0)
            if src in self.resolver.material_replacements:
                del self.resolver.material_replacements[src]
                self.refresh_tree()

    def clear_all_overrides(self) -> None:
        if self.resolver.material_replacements:
            self.resolver.material_replacements.clear()
            self.refresh_tree()


class NamespaceMappingDialog(QDialog):
    def __init__(self, parent: QWidget, resolver: AdvancedRecipeResolver) -> None:
        super().__init__(parent)
        self.setWindowTitle("Namespace & Tag Custom Remappings")
        self.resize(520, 400)
        self.resolver = resolver

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Configure Custom Namespace/Tag Remappings:"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Source Namespace/Tag", "Target Namespace"])
        self.tree.header().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.tree)

        self.refresh_tree()

        entry_layout = QHBoxLayout()
        entry_layout.addWidget(QLabel("From:"))
        self.src_entry = QLineEdit()
        entry_layout.addWidget(self.src_entry)

        entry_layout.addWidget(QLabel("To:"))
        self.tgt_entry = QLineEdit()
        entry_layout.addWidget(self.tgt_entry)

        add_btn = QPushButton("Add/Update Link")
        add_btn.clicked.connect(self.add_mapping)
        entry_layout.addWidget(add_btn)

        layout.addLayout(entry_layout)

        btn_layout = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected Link")
        remove_btn.clicked.connect(self.remove_mapping)
        btn_layout.addWidget(remove_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def refresh_tree(self) -> None:
        self.tree.clear()
        for k, v in self.resolver.namespace_mappings.items():
            self.tree.addTopLevelItem(QTreeWidgetItem([k, v]))

    def add_mapping(self) -> None:
        src = self.src_entry.text().strip()
        tgt = self.tgt_entry.text().strip()
        if src and tgt:
            self.resolver.namespace_mappings[src] = tgt
            self.refresh_tree()
            self.src_entry.clear()
            self.tgt_entry.clear()

    def remove_mapping(self) -> None:
        selected = self.tree.selectedItems()
        if selected:
            src = selected[0].text(0)
            if src in self.resolver.namespace_mappings:
                del self.resolver.namespace_mappings[src]
                self.refresh_tree()


class ItemCapDialog(QDialog):
    def __init__(self, parent: QWidget, resolver: AdvancedRecipeResolver) -> None:
        super().__init__(parent)
        self.setWindowTitle("Item Max Crafting Caps")
        self.resize(520, 400)
        self.resolver = resolver

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Set Maximum Craftable Limits per Item:"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item ID", "Max Craft Limit"])
        self.tree.header().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.tree)

        self.refresh_tree()

        entry_layout = QHBoxLayout()
        entry_layout.addWidget(QLabel("Item ID:"))
        self.item_entry = QLineEdit()
        entry_layout.addWidget(self.item_entry)

        entry_layout.addWidget(QLabel("Cap:"))
        self.cap_spin = QDoubleSpinBox()
        self.cap_spin.setRange(0, 1000000)
        self.cap_spin.setValue(10)
        entry_layout.addWidget(self.cap_spin)

        set_btn = QPushButton("Set Cap")
        set_btn.clicked.connect(self.add_cap)
        entry_layout.addWidget(set_btn)

        layout.addLayout(entry_layout)

        btn_layout = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected Cap")
        remove_btn.clicked.connect(self.remove_cap)
        btn_layout.addWidget(remove_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def refresh_tree(self) -> None:
        self.tree.clear()
        for k, v in self.resolver.item_caps.items():
            self.tree.addTopLevelItem(QTreeWidgetItem([k, str(v)]))

    def add_cap(self) -> None:
        item_id = self.resolver.normalize_id(self.item_entry.text().strip())
        cap = self.cap_spin.value()
        if item_id:
            self.resolver.item_caps[item_id] = cap
            self.refresh_tree()
            self.item_entry.clear()

    def remove_cap(self) -> None:
        selected = self.tree.selectedItems()
        if selected:
            item_id = selected[0].text(0)
            if item_id in self.resolver.item_caps:
                del self.resolver.item_caps[item_id]
                self.refresh_tree()


class RepoManagerDialog(QDialog):
    def __init__(self, parent: QWidget, repos_list: List[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Repositories")
        self.resize(600, 400)
        self.repos = list(repos_list)
        self.result_repos: Optional[List[str]] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Active Mod Repository Sources:"))

        self.repo_listwidget = QListWidget()
        layout.addWidget(self.repo_listwidget)

        self.refresh_list()

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Repo Directory...")
        add_btn.clicked.connect(self.add_repo)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_repo)
        btn_layout.addWidget(remove_btn)

        btn_layout.addStretch()
        save_btn = QPushButton("Save & Scan")
        save_btn.clicked.connect(self.save_and_close)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def refresh_list(self) -> None:
        self.repo_listwidget.clear()
        for r in self.repos:
            self.repo_listwidget.addItem(r)

    def add_repo(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Mod Repository Folder")
        if path and path not in self.repos:
            self.repos.append(path)
            self.refresh_list()

    def remove_repo(self) -> None:
        selected = self.repo_listwidget.currentRow()
        if selected >= 0:
            del self.repos[selected]
            self.refresh_list()

    def save_and_close(self) -> None:
        self.result_repos = self.repos
        self.accept()


# ==================== MAIN APPLICATION GUI ====================
class ModMaterialCalculatorGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mod Material & Pattern Calculator")
        self.resize(1240, 860)

        self.db_file = get_user_data_filepath("user_data.json")
        self.resolver = AdvancedRecipeResolver()
        
        self.active_repos: List[str] = []
        self.cart: Dict[str, int] = {}
        self.signals = WorkerSignals()

        self._cached_raw_totals: Dict[str, float] = {}
        self._cached_method_totals: Dict[str, Dict[str, Any]] = {}

        # Search Debouncing Timer (250ms)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.filter_items)

        self.signals.rescan_done.connect(self._on_rescan_complete)
        self.signals.calc_done.connect(self._on_calculation_finished)

        self.load_user_data()
        self.setup_ui()

        if self.active_repos:
            self.rescan_all_repos()

    def load_user_data(self) -> None:
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.active_repos = data.get("active_repos", [])
                    self.cart = data.get("cart", {})
                    self.resolver.namespace_mappings = data.get("namespace_mappings", {})
                    for legacy_key in ["#c", "c", "#forge", "forge"]:
                        if self.resolver.namespace_mappings.get(legacy_key) == "minecraft":
                            del self.resolver.namespace_mappings[legacy_key]

                    self.resolver.preferred_recipes = data.get("preferred_recipes", {})
                    self.resolver.item_caps = data.get("item_caps", {})
                    self.resolver.material_replacements = data.get("material_replacements", {})
                    self.resolver.owned_inventory = defaultdict(int, data.get("owned_inventory", {}))
                    self.resolver.raw_overrides = set(data.get("raw_overrides", [
                        "minecraft:iron_ingot", "minecraft:gold_ingot", "minecraft:redstone",
                        "minecraft:copper_ingot", "minecraft:quartz", "minecraft:stick",
                        "ae2:certus_quartz_crystal", "ae2:silicon", "ae2:sky_stone_block"
                    ]))
            except Exception as e:
                logging.error(f"Failed to load user data: {e}")

    def save_user_data(self) -> None:
        data = {
            "active_repos": self.active_repos,
            "cart": self.cart,
            "namespace_mappings": self.resolver.namespace_mappings,
            "preferred_recipes": self.resolver.preferred_recipes,
            "item_caps": self.resolver.item_caps,
            "material_replacements": self.resolver.material_replacements,
            "owned_inventory": dict(self.resolver.owned_inventory),
            "raw_overrides": list(self.resolver.raw_overrides)
        }
        dir_name = os.path.dirname(self.db_file) or "."
        try:
            with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
                json.dump(data, tf, indent=4)
                temp_name = tf.name
            os.replace(temp_name, self.db_file)
        except Exception as e:
            logging.error(f"Failed to save user data atomically: {e}")

    def setup_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)

        # Top System Controls Box
        top_group = QGroupBox(" System Management ")
        top_layout = QHBoxLayout(top_group)

        self.repo_label = QLabel(f"Active Repositories: {len(self.active_repos)}")
        top_layout.addWidget(self.repo_label)

        btn_manage = QPushButton("Manage Repos...")
        btn_manage.clicked.connect(self.open_repo_manager)
        top_layout.addWidget(btn_manage)

        btn_rescan = QPushButton("Rescan Repositories")
        btn_rescan.clicked.connect(self.rescan_all_repos)
        top_layout.addWidget(btn_rescan)

        btn_links = QPushButton("Custom Namespace Links...")
        btn_links.clicked.connect(self.open_namespace_manager)
        top_layout.addWidget(btn_links)

        btn_prefs = QPushButton("Recipe Preferences...")
        btn_prefs.clicked.connect(self.open_recipe_preference_manager)
        top_layout.addWidget(btn_prefs)

        btn_overrides = QPushButton("Material Overrides...")
        btn_overrides.clicked.connect(self.open_material_replacements_manager)
        top_layout.addWidget(btn_overrides)

        btn_caps = QPushButton("Set Item Max Caps...")
        btn_caps.clicked.connect(self.open_item_cap_manager)
        top_layout.addWidget(btn_caps)

        top_layout.addStretch()
        root_layout.addWidget(top_group)

        # Main Splitter
        main_splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(main_splitter, stretch=1)

        # Left Column Panel
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        search_header_layout = QHBoxLayout()
        search_header_layout.addWidget(QLabel("Search Patterns / Products:"))
        search_header_layout.addStretch()

        self.unrecognized_checkbox = QCheckBox("Include unrecognized patterns")
        self.unrecognized_checkbox.setToolTip("Include items and patterns from the repository that do not have standard recipe definitions.")
        self.unrecognized_checkbox.stateChanged.connect(self.filter_items)
        search_header_layout.addWidget(self.unrecognized_checkbox)

        left_layout.addLayout(search_header_layout)

        self.search_entry = QLineEdit()
        self.search_entry.textChanged.connect(lambda: self.search_timer.start())
        left_layout.addWidget(self.search_entry)

        self.item_listwidget = QListWidget()
        self.item_listwidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.item_listwidget.customContextMenuRequested.connect(self.open_search_context_menu)
        self.item_listwidget.itemDoubleClicked.connect(self.open_recipe_viewer_listbox)
        left_layout.addWidget(self.item_listwidget)

        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("Qty:"))

        self.qty_spinbox = QSpinBox()
        self.qty_spinbox.setRange(1, 1000000)
        self.qty_spinbox.setValue(1)
        add_layout.addWidget(self.qty_spinbox)

        btn_add_cart = QPushButton("Add to Cart")
        btn_add_cart.clicked.connect(self.add_selected_item)
        add_layout.addWidget(btn_add_cart, stretch=1)

        left_layout.addLayout(add_layout)
        main_splitter.addWidget(left_widget)

        # Right Column Panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Vertical Splitter allowing Cart resizing
        right_splitter = QSplitter(Qt.Vertical)

        # Cart Box Widget with In-Stock / Owned Column
        cart_group = QGroupBox(" Selected Items Cart ")
        cart_layout = QVBoxLayout(cart_group)

        self.cart_tree = QTreeWidget()
        self.cart_tree.setHeaderLabels(["Item ID", "Qty Needed", "In Stock / Owned"])
        self.cart_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cart_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.cart_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.cart_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cart_tree.customContextMenuRequested.connect(self.open_cart_context_menu)
        self.cart_tree.itemDoubleClicked.connect(self.open_recipe_viewer_cart)
        cart_layout.addWidget(self.cart_tree)

        cart_btn_layout = QHBoxLayout()
        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self.remove_cart_item)
        cart_btn_layout.addWidget(btn_remove)

        btn_clear = QPushButton("Clear Cart")
        btn_clear.clicked.connect(self.clear_cart)
        cart_btn_layout.addWidget(btn_clear)

        cart_btn_layout.addStretch()
        cart_layout.addLayout(cart_btn_layout)

        right_splitter.addWidget(cart_group)

        # Material Breakdown Group
        report_group = QGroupBox(" Material Breakdown Report ")
        report_layout = QVBoxLayout(report_group)

        report_splitter = QSplitter(Qt.Vertical)

        # Raw Materials Section
        raw_widget = QWidget()
        raw_layout = QVBoxLayout(raw_widget)
        raw_layout.setContentsMargins(0, 0, 0, 0)

        raw_header_layout = QHBoxLayout()
        raw_header_layout.addWidget(QLabel("Remaining Raw Materials Required:"))
        raw_header_layout.addStretch()

        btn_copy_raw = QPushButton("Copy Raw Materials")
        btn_copy_raw.clicked.connect(self.copy_raw_materials_to_clipboard)
        raw_header_layout.addWidget(btn_copy_raw)

        raw_header_layout.addWidget(QLabel("Sort Materials By:"))
        self.raw_sort_combo = QComboBox()

        self.raw_sort_combo.addItems([
            "Highest Quantity First",
            "Lowest Quantity First",
            "Alphabetical (A-Z)",
            "Namespace (A-Z)",
            "Tags First (Grouped)"
        ])
        self.raw_sort_combo.currentIndexChanged.connect(self.refresh_raw_materials_display)
        raw_header_layout.addWidget(self.raw_sort_combo)

        raw_layout.addLayout(raw_header_layout)

        # Sectioned Columns for Raw Materials (Including In Stock Column)
        self.report_tree = QTreeWidget()
        self.report_tree.setHeaderLabels(["Category", "Namespace", "Item / Tag Name", "Remaining Needed", "In Stock / Owned", "Stacks / Remainder"])
        self.report_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.report_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.report_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.report_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.report_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.report_tree.header().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.report_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.report_tree.customContextMenuRequested.connect(self.open_raw_tree_context_menu)
        self.report_tree.itemDoubleClicked.connect(self.open_replacement_dialog)
        raw_layout.addWidget(self.report_tree)

        report_splitter.addWidget(raw_widget)

        # Crafting Breakdown Section
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)

        sort_header_layout = QHBoxLayout()
        sort_header_layout.addWidget(QLabel("Remaining Processing / Crafting Methods Breakdown:"))
        sort_header_layout.addStretch()

        btn_copy_breakdown = QPushButton("Copy Breakdown")
        btn_copy_breakdown.clicked.connect(self.copy_breakdown_to_clipboard)
        sort_header_layout.addWidget(btn_copy_breakdown)

        sort_header_layout.addWidget(QLabel("Sort Steps By:"))
        self.craft_sort_combo = QComboBox()

        self.craft_sort_combo.addItems([
            "Prerequisites First (Dependency Order)",
            "Step Level (Ascending)",
            "Step Level (Descending)",
            "Highest Quantity First",
            "Lowest Quantity First",
            "Alphabetical (A-Z)",
            "Namespace (A-Z)"
        ])
        self.craft_sort_combo.currentIndexChanged.connect(self.refresh_breakdown_display)
        sort_header_layout.addWidget(self.craft_sort_combo)

        text_layout.addLayout(sort_header_layout)

        # Clickable QTextBrowser Links with Context Menu
        self.report_text = QTextBrowser()
        self.report_text.setOpenLinks(False)
        self.report_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.report_text.customContextMenuRequested.connect(self.open_breakdown_context_menu)
        self.report_text.anchorClicked.connect(self.on_breakdown_link_clicked)
        text_layout.addWidget(self.report_text)

        report_splitter.addWidget(text_widget)
        report_splitter.setStretchFactor(0, 2)
        report_splitter.setStretchFactor(1, 3)

        report_layout.addWidget(report_splitter)
        right_splitter.addWidget(report_group)

        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 3)

        right_layout.addWidget(right_splitter)

        self.status_label = QLabel("Ready.")
        status_font = QFont("Helvetica", 9, QFont.Normal)
        status_font.setItalic(True)
        self.status_label.setFont(status_font)
        right_layout.addWidget(self.status_label)

        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)

        self.refresh_cart_ui()
        self.trigger_async_calculation()

    # ==================== CLICKABLE BREAKDOWN LINKS ====================
    def on_breakdown_link_clicked(self, url: QUrl) -> None:
        raw_href = url.toString()
        if raw_href.startswith("item:"):
            item_id = raw_href[5:]
            if item_id.startswith("#"):
                TagInspectorDialog(self, self.resolver, item_id, callback=self.on_recipe_preference_changed).exec()
            else:
                ItemInspectorDialog(self, self.resolver, item_id, callback=self.on_recipe_preference_changed).exec()
        elif raw_href.startswith("override:"):
            item_id = raw_href[9:]
            is_overridden = self.resolver.toggle_raw_override(item_id)
            self.save_user_data()
            self.trigger_async_calculation()
            act_str = "Treating as Base Raw Material" if is_overridden else "Crafting Recipe Restored"
            self.status_label.setText(f"Override updated for '{item_id}': {act_str}.")

    def open_breakdown_context_menu(self, position: Any) -> None:
        anchor = self.report_text.anchorAt(position)
        if not anchor:
            return
        if anchor.startswith("item:") or anchor.startswith("override:"):
            clean_id = anchor.split(":", 1)[1]
            menu = QMenu(self)
            
            act_inspect = QAction(f"Inspect '{clean_id}'...", self)
            act_inspect.triggered.connect(lambda: ItemInspectorDialog(self, self.resolver, clean_id, callback=self.on_recipe_preference_changed).exec())
            menu.addAction(act_inspect)

            is_ov = clean_id in self.resolver.raw_overrides
            ov_text = "🛠️ Restore Crafting Recipe" if is_ov else "🛑 Override Step (Treat as Base Raw Material)"
            act_ov = QAction(ov_text, self)
            act_ov.triggered.connect(lambda: self.toggle_raw_override_and_recalc(clean_id))
            menu.addAction(act_ov)

            act_copy = QAction("Copy Item ID", self)
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(clean_id))
            menu.addAction(act_copy)

            menu.exec(self.report_text.viewport().mapToGlobal(position))

    def toggle_raw_override_and_recalc(self, item_id: str) -> None:
        self.resolver.toggle_raw_override(item_id)
        self.save_user_data()
        self.trigger_async_calculation()

    # ==================== MANAGERIAL DIALOG OPENERS ====================
    def on_inventory_changed(self) -> None:
        self.save_user_data()
        self.refresh_cart_ui()
        self.trigger_async_calculation()

    def open_recipe_viewer_listbox(self, item: Any) -> None:
        item_id = item.data(Qt.UserRole) or item.text()
        if item_id and not item_id.startswith("["):
            ItemInspectorDialog(self, self.resolver, item_id, callback=self.on_recipe_preference_changed).exec()

    def open_recipe_viewer_cart(self, item: Any, column: int) -> None:
        item_id = item.text(0)
        if item_id:
            ItemInspectorDialog(self, self.resolver, item_id, callback=self.on_recipe_preference_changed).exec()

    def open_replacement_dialog(self, item: Any, column: int) -> None:
        cat = item.text(0)
        ns = item.text(1)
        name = item.text(2)
        item_id = f"#{ns}:{name}" if cat == "Tag" else f"{ns}:{name}"
        MaterialReplacementDialog(self, self.resolver, item_id, self.trigger_async_calculation).exec()

    def open_recipe_preference_manager(self) -> None:
        dlg = RecipePreferenceManagerDialog(self, self.resolver, callback=self.on_recipe_preference_changed)
        if dlg.exec():
            self.save_user_data()
            self.trigger_async_calculation()

    def open_material_replacements_manager(self) -> None:
        dlg = MaterialReplacementManagerDialog(self, self.resolver)
        if dlg.exec():
            self.save_user_data()
            self.trigger_async_calculation()

    def open_namespace_manager(self) -> None:
        dlg = NamespaceMappingDialog(self, self.resolver)
        if dlg.exec():
            self.save_user_data()
            self.trigger_async_calculation()

    def open_item_cap_manager(self) -> None:
        dlg = ItemCapDialog(self, self.resolver)
        if dlg.exec():
            self.save_user_data()
            self.trigger_async_calculation()

    def open_repo_manager(self) -> None:
        dlg = RepoManagerDialog(self, self.active_repos)
        if dlg.exec() and dlg.result_repos is not None:
            self.active_repos = dlg.result_repos
            self.repo_label.setText(f"Active Repositories: {len(self.active_repos)}")
            self.rescan_all_repos()
            self.save_user_data()

    def on_recipe_preference_changed(self) -> None:
        self.save_user_data()
        self.trigger_async_calculation()

    # ==================== CONTEXT MENUS & CLIPBOARD ====================
    def open_search_context_menu(self, position: Any) -> None:
        item = self.item_listwidget.itemAt(position)
        if not item:
            return
        clean_id = item.data(Qt.UserRole) or item.text()
        if clean_id.startswith("["):
            return

        menu = QMenu(self)
        act_inspect = QAction(f"Inspect '{clean_id}'...", self)
        act_inspect.triggered.connect(lambda: ItemInspectorDialog(self, self.resolver, clean_id, callback=self.on_recipe_preference_changed).exec())
        menu.addAction(act_inspect)

        menu.exec(self.item_listwidget.viewport().mapToGlobal(position))

    def open_raw_tree_context_menu(self, position: Any) -> None:
        item = self.report_tree.itemAt(position)
        if not item:
            return
        cat, ns, name = item.text(0), item.text(1), item.text(2)
        clean_id = f"#{ns}:{name}" if cat == "Tag" else f"{ns}:{name}"

        menu = QMenu(self)
        act_inspect = QAction(f"Inspect '{clean_id}'...", self)
        act_inspect.triggered.connect(lambda: ItemInspectorDialog(self, self.resolver, clean_id, callback=self.on_recipe_preference_changed).exec())
        menu.addAction(act_inspect)

        is_ov = clean_id in self.resolver.raw_overrides
        ov_text = "🛠️ Restore Crafting Recipe (Remove Raw Override)" if is_ov else "🛑 Override Step (Treat as Base Raw Material)"
        act_ov = QAction(ov_text, self)
        act_ov.triggered.connect(lambda: self.toggle_raw_override_and_recalc(clean_id))
        menu.addAction(act_ov)

        act_replace = QAction("Replace/Override Material...", self)
        act_replace.triggered.connect(lambda: MaterialReplacementDialog(self, self.resolver, clean_id, self.trigger_async_calculation).exec())
        menu.addAction(act_replace)

        act_copy_id = QAction(f"Copy ID ('{clean_id}')", self)
        act_copy_id.triggered.connect(lambda: QApplication.clipboard().setText(clean_id))
        menu.addAction(act_copy_id)

        menu.exec(self.report_tree.viewport().mapToGlobal(position))

    def open_cart_context_menu(self, position: Any) -> None:
        item = self.cart_tree.itemAt(position)
        if not item:
            return
        item_id = item.text(0)
        menu = QMenu(self)

        act_inspect = QAction("Inspect Item & Pattern Series...", self)
        act_inspect.triggered.connect(lambda: ItemInspectorDialog(self, self.resolver, item_id, callback=self.on_recipe_preference_changed).exec())
        menu.addAction(act_inspect)

        act_copy_id = QAction("Copy Item ID", self)
        act_copy_id.triggered.connect(lambda: QApplication.clipboard().setText(item_id))
        menu.addAction(act_copy_id)

        act_remove = QAction("Remove Item", self)
        act_remove.triggered.connect(self.remove_cart_item)
        menu.addAction(act_remove)

        menu.exec(self.cart_tree.viewport().mapToGlobal(position))

    def copy_raw_materials_to_clipboard(self) -> None:
        lines = []
        root = self.report_tree.invisibleRootItem()
        for i in range(root.childCount()):
            c = root.child(i)
            lines.append(f"[{c.text(0)}] {c.text(1)}:{c.text(2)} -> Remaining Needed: {c.text(3)} ({c.text(5)})")
        if lines:
            QApplication.clipboard().setText("\n".join(lines))
            self.status_label.setText("Raw materials list copied to clipboard.")

    def copy_breakdown_to_clipboard(self) -> None:
        text = self.report_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_label.setText("Crafting breakdown copied to clipboard.")

    # ==================== DATA PROCESSING & CALCULATION ====================
    def rescan_all_repos(self) -> None:
        self.status_label.setText("Scanning repositories...")
        threading.Thread(target=self._rescan_thread, daemon=True).start()

    def _rescan_thread(self) -> None:
        self.resolver.scan_repositories(self.active_repos)
        self.signals.rescan_done.emit()

    def _on_rescan_complete(self) -> None:
        self.filter_items()
        self.status_label.setText("Scanning complete.")
        self.trigger_async_calculation()

    def filter_items(self) -> None:
        query = self.search_entry.text().lower().strip()
        self.item_listwidget.clear()

        include_unrecognized = self.unrecognized_checkbox.isChecked()

        if include_unrecognized:
            all_items = sorted(list(self.resolver.all_known_items))
        else:
            all_items = sorted(list(self.resolver.recipes.keys()))

        if not all_items:
            self.item_listwidget.addItem("[ No Repositories Loaded - Click 'Manage Repos...' above ]")
            return

        for item in all_items:
            if query in item.lower():
                recipe_count = len(self.resolver.recipes.get(item, []))
                if recipe_count > 1:
                    badge = f"  [⚡ {recipe_count} Recipes]"
                elif recipe_count == 0:
                    badge = "  [❓ Unrecognized / Raw Material]"
                else:
                    badge = ""
                
                widget_item = QListWidgetItem(f"{item}{badge}")
                widget_item.setData(Qt.UserRole, item)
                self.item_listwidget.addItem(widget_item)

    def add_selected_item(self) -> None:
        items = self.item_listwidget.selectedItems()
        if not items:
            return
        item_id = items[0].data(Qt.UserRole) or items[0].text()
        if item_id.startswith("["):
            return

        qty = self.qty_spinbox.value()
        self.cart[item_id] = self.cart.get(item_id, 0) + qty
        self.refresh_cart_ui()
        self.save_user_data()
        self.trigger_async_calculation()

    def remove_cart_item(self) -> None:
        selected = self.cart_tree.selectedItems()
        if not selected:
            return
        item_id = selected[0].text(0)
        if item_id in self.cart:
            del self.cart[item_id]
            self.refresh_cart_ui()
            self.save_user_data()
            self.trigger_async_calculation()

    def clear_cart(self) -> None:
        self.cart.clear()
        self.refresh_cart_ui()
        self.save_user_data()
        self.trigger_async_calculation()

    def refresh_cart_ui(self) -> None:
        self.cart_tree.blockSignals(True)
        self.cart_tree.clear()
        for item_id, qty in self.cart.items():
            tree_item = QTreeWidgetItem([item_id, "", ""])
            self.cart_tree.addTopLevelItem(tree_item)

            spin_needed = QSpinBox()
            spin_needed.setRange(1, 1000000)
            spin_needed.setValue(qty)
            spin_needed.valueChanged.connect(lambda val, i_id=item_id: self.on_cart_qty_changed(i_id, val))
            self.cart_tree.setItemWidget(tree_item, 1, spin_needed)

            spin_owned = QSpinBox()
            spin_owned.setRange(0, 1000000)
            spin_owned.setValue(self.resolver.owned_inventory.get(item_id, 0))
            spin_owned.valueChanged.connect(lambda val, i_id=item_id: self.on_cart_owned_qty_changed(i_id, val))
            self.cart_tree.setItemWidget(tree_item, 2, spin_owned)

        self.cart_tree.blockSignals(False)

    def on_cart_qty_changed(self, item_id: str, new_qty: int) -> None:
        if item_id in self.cart:
            self.cart[item_id] = new_qty
            self.save_user_data()
            self.trigger_async_calculation()

    def on_cart_owned_qty_changed(self, item_id: str, new_owned_qty: int) -> None:
        if new_owned_qty > 0:
            self.resolver.owned_inventory[item_id] = new_owned_qty
        else:
            if item_id in self.resolver.owned_inventory:
                del self.resolver.owned_inventory[item_id]
        self.save_user_data()
        self.trigger_async_calculation()

    def on_raw_owned_qty_changed(self, item_id: str, new_owned_qty: int) -> None:
        if new_owned_qty > 0:
            self.resolver.owned_inventory[item_id] = new_owned_qty
        else:
            if item_id in self.resolver.owned_inventory:
                del self.resolver.owned_inventory[item_id]
        self.save_user_data()
        self.refresh_cart_ui()
        self.trigger_async_calculation()

    def trigger_async_calculation(self) -> None:
        if not self.cart:
            self.report_tree.clear()
            self.report_text.clear()
            self._cached_raw_totals.clear()
            self._cached_method_totals.clear()
            if not self.active_repos:
                self.report_text.setText("[ Welcome! Click 'Manage Repos...' at the top to add your Minecraft mod JSON repository folders. ]")
            else:
                self.report_text.setText("[ Cart is currently empty. Select items on the left and click 'Add to Cart'. ]")
            self.status_label.setText("Ready.")
            return

        self.status_label.setText("Calculating remaining materials in background...")
        cart_snapshot = dict(self.cart)
        threading.Thread(target=self._async_calculate_worker, args=(cart_snapshot,), daemon=True).start()

    def _async_calculate_worker(self, cart_snapshot: Dict[str, int]) -> None:
        grand_raw_totals: Dict[str, float] = defaultdict(float)
        grand_method_totals: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(lambda: {
            "amount": 0,
            "inputs": defaultdict(float)
        }))

        item_usage_tracker: Dict[str, float] = defaultdict(float)
        
        with self.resolver._lock:
            inventory_tracker = defaultdict(int, self.resolver.owned_inventory.copy())

        for item, qty in cart_snapshot.items():
            raw_mats, methods = self.resolver.get_raw_materials(
                item, target_amount=qty, item_usage_tracker=item_usage_tracker, inventory_tracker=inventory_tracker
            )
            for r_id, r_qty in raw_mats.items():
                grand_raw_totals[r_id] += r_qty
            for m_type, items in methods.items():
                for sub_item, sub_data in items.items():
                    grand_method_totals[m_type][sub_item]["amount"] += sub_data["amount"]
                    for p_inp, p_qty in sub_data["inputs"].items():
                        grand_method_totals[m_type][sub_item]["inputs"][p_inp] += p_qty

        sanitized_methods = {}
        for m_type, items_dict in grand_method_totals.items():
            sanitized_methods[m_type] = {}
            for item_id, data in items_dict.items():
                sanitized_methods[m_type][item_id] = {
                    "amount": data["amount"],
                    "inputs": dict(data["inputs"])
                }

        self.signals.calc_done.emit(dict(grand_raw_totals), sanitized_methods)

    def _on_calculation_finished(self, grand_raw_totals: Dict[str, float], grand_method_totals: Dict[str, Dict[str, Any]]) -> None:
        self._cached_raw_totals = grand_raw_totals
        self._cached_method_totals = grand_method_totals
        
        self.refresh_raw_materials_display()
        self.refresh_breakdown_display()
        self.status_label.setText("Calculation up to date.")

    def refresh_raw_materials_display(self) -> None:
        if not self._cached_raw_totals:
            return

        self.report_tree.blockSignals(True)
        self.report_tree.clear()
        sort_mode = self.raw_sort_combo.currentText()
        raw_list = list(self._cached_raw_totals.items())

        if "Highest Quantity" in sort_mode:
            raw_list.sort(key=lambda x: x[1], reverse=True)
        elif "Lowest Quantity" in sort_mode:
            raw_list.sort(key=lambda x: x[1])
        elif "Alphabetical" in sort_mode:
            raw_list.sort(key=lambda x: x[0])
        elif "Namespace" in sort_mode:
            raw_list.sort(key=lambda x: (
                x[0].lstrip("#").split(":", 1)[0] if ":" in x[0] else "minecraft",
                x[0]
            ))
        elif "Tags First" in sort_mode:
            raw_list.sort(key=lambda x: (not x[0].startswith("#"), -x[1]))

        for mat, amt in raw_list:
            amt_int = int(math.ceil(amt))
            stacks = amt_int // 64
            rem_items = amt_int % 64

            stack_str = f"{stacks} stacks + {rem_items}" if stacks >= 1 else "-"

            is_tag = mat.startswith("#")
            cat_str = "Tag" if is_tag else "Item"
            if mat in self.resolver.raw_overrides:
                cat_str += " [🛑 Overridden]"

            clean_mat = mat.lstrip("#")
            ns, item_name = clean_mat.split(":", 1) if ":" in clean_mat else ("minecraft", clean_mat)

            tree_item = QTreeWidgetItem([cat_str, ns, item_name, str(amt_int), "", stack_str])
            self.report_tree.addTopLevelItem(tree_item)

            spin_owned = QSpinBox()
            spin_owned.setRange(0, 1000000)
            spin_owned.setValue(self.resolver.owned_inventory.get(mat, 0))
            spin_owned.valueChanged.connect(lambda val, m_id=mat: self.on_raw_owned_qty_changed(m_id, val))
            self.report_tree.setItemWidget(tree_item, 4, spin_owned)

        self.report_tree.blockSignals(False)

    def _calculate_dependency_depths(self, grand_method_totals: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
        """Calculates crafting tree depth with tag substitutions and tag graph resolution."""
        craft_items = set()
        item_inputs = defaultdict(set)

        for method, items_dict in grand_method_totals.items():
            for item_id, data in items_dict.items():
                craft_items.add(item_id)
                if isinstance(data, dict):
                    for inp_id in data.get("inputs", {}).keys():
                        actual_inps = set()
                        resolved_inp = self.resolver.material_replacements.get(inp_id, inp_id)
                        if resolved_inp in craft_items:
                            actual_inps.add(resolved_inp)
                        elif inp_id.startswith("#"):
                            tag_members = self.resolver.get_tag_members_recursive(inp_id)
                            for m in tag_members:
                                if m in craft_items:
                                    actual_inps.add(m)
                            if not actual_inps:
                                matching = self.resolver.get_items_matching_tag(inp_id)
                                for m in matching:
                                    if m in craft_items:
                                        actual_inps.add(m)
                        else:
                            actual_inps.add(resolved_inp)

                        for resolved in actual_inps:
                            item_inputs[item_id].add(resolved)

        depths: Dict[str, int] = {}

        def get_depth(item_id: str, visited: Optional[Set[str]] = None) -> int:
            if visited is None:
                visited = set()
            if item_id in depths:
                return depths[item_id]
            if item_id in visited:
                return 0
            visited.add(item_id)

            max_input_depth = -1
            for inp_id in item_inputs[item_id]:
                if inp_id in craft_items and inp_id != item_id:
                    max_input_depth = max(max_input_depth, get_depth(inp_id, visited.copy()))

            depths[item_id] = max_input_depth + 1
            return depths[item_id]

        for item_id in craft_items:
            get_depth(item_id)

        return depths

    def refresh_breakdown_display(self) -> None:
        if not self._cached_method_totals:
            return

        sort_mode = self.craft_sort_combo.currentText()
        depths = self._calculate_dependency_depths(self._cached_method_totals)

        html_blocks = []

        if "Step Level" in sort_mode:
            flat_items = []
            for method, items_dict in self._cached_method_totals.items():
                for item_id, data in items_dict.items():
                    flat_items.append((item_id, data, method))

            level_groups = defaultdict(list)
            for item_id, data, method in flat_items:
                lvl = depths.get(item_id, 0)
                level_groups[lvl].append((item_id, data, method))

            sorted_levels = sorted(level_groups.keys(), reverse=("Descending" in sort_mode))

            for lvl in sorted_levels:
                html_blocks.append(f"<h3 style='margin-bottom:4px; color:#2c3e50;'>=== [ Step Level {lvl} ] ===</h3>")
                items_in_lvl = level_groups[lvl]
                items_in_lvl.sort(key=lambda x: -(x[1]["amount"] if isinstance(x[1], dict) else x[1]))

                for item_id, data, method in items_in_lvl:
                    if isinstance(data, dict):
                        amt = int(math.ceil(data["amount"]))
                        inputs = data.get("inputs", {})
                        
                        action = "Craft"
                        m_lower = method.lower()
                        if "smelting" in m_lower or "furnace" in m_lower or "blasting" in m_lower:
                            action = "Smelt"
                        elif "crushing" in m_lower or "pulverizing" in m_lower or "grinding" in m_lower:
                            action = "Crush"

                        recipe_count = len(self.resolver.recipes.get(item_id, []))
                        multi_badge = f" <font color='#e67e22' size='2'><b>[⚡ {recipe_count} Recipes]</b></font>" if recipe_count > 1 else ""
                        origin_badge = f" <font color='#e74c3c' size='2'><b>[⚠️ Origin Unknown]</b></font>" if self.resolver.is_self_referential(item_id) else ""
                        method_tag = f" <font color='#8e44ad' size='2'><i>(via {method})</i></font>"
                        override_link = f" <a href='override:{item_id}' style='color:#e74c3c; font-size:11px; text-decoration:none;'>[🛑 Override Step]</a>"

                        html_blocks.append(
                            f"<div style='margin-top:6px;'><b>• {action} {amt}x <a href='item:{item_id}' style='color:#2980b9; text-decoration:none;'>{item_id}</a></b>{multi_badge}{origin_badge}{method_tag}{override_link}</div>"
                        )

                        if inputs:
                            html_blocks.append("<div style='margin-left: 24px; margin-top:2px; margin-bottom:6px; color:#555;'>")
                            html_blocks.append("<i>↳ Inputs Required:</i><br/>")
                            for ing_id, q in inputs.items():
                                ing_qty = int(math.ceil(q))
                                ing_recipe_count = len(self.resolver.recipes.get(ing_id, []))
                                ing_badge = f" <font color='#e67e22' size='1'>[⚡ {ing_recipe_count} Recipes]</font>" if ing_recipe_count > 1 else ""
                                ing_origin = f" <font color='#e74c3c' size='1'>[⚠️ Origin Unknown]</font>" if self.resolver.is_self_referential(ing_id) else ""

                                tag_badge = ""
                                if ing_id.startswith("#"):
                                    if ing_id in self.resolver.material_replacements:
                                        replaced_with = self.resolver.material_replacements[ing_id]
                                        tag_badge = f" <font color='#27ae60' size='1'><b>[🏷️ Selected: {replaced_with}]</b></font>"
                                    else:
                                        matches = self.resolver.get_items_matching_tag(ing_id)
                                        if matches:
                                            tag_badge = f" <font color='#2980b9' size='1'><b>[🏷️ {len(matches)} Options Available]</b></font>"

                                html_blocks.append(
                                    f"&nbsp;&nbsp;&nbsp;&nbsp;• {ing_qty}x <a href='item:{ing_id}' style='color:#27ae60; text-decoration:none;'>{ing_id}</a>{ing_badge}{ing_origin}{tag_badge}<br/>"
                                )
                            html_blocks.append("</div>")
                    else:
                        amt = int(math.ceil(data))
                        method_tag = f" <font color='#8e44ad' size='2'><i>(via {method})</i></font>"
                        override_link = f" <a href='override:{item_id}' style='color:#e74c3c; font-size:11px; text-decoration:none;'>[🛑 Override Step]</a>"
                        html_blocks.append(f"<div>• Process {amt}x <a href='item:{item_id}' style='color:#2980b9;'>{item_id}</a>{method_tag}{override_link}</div>")

        else:
            for method, items_dict in self._cached_method_totals.items():
                html_blocks.append(f"<h3 style='margin-bottom:4px; color:#2c3e50;'>=== [ Method: {method} ] ===</h3>")
                items_list = list(items_dict.items())

                if "Prerequisites First" in sort_mode:
                    items_list.sort(key=lambda x: (
                        depths.get(x[0], 0),
                        -(x[1]["amount"] if isinstance(x[1], dict) else x[1])
                    ))
                elif "Highest Quantity" in sort_mode:
                    items_list.sort(key=lambda x: x[1]["amount"] if isinstance(x[1], dict) else x[1], reverse=True)
                elif "Lowest Quantity" in sort_mode:
                    items_list.sort(key=lambda x: x[1]["amount"] if isinstance(x[1], dict) else x[1])
                elif "Alphabetical" in sort_mode:
                    items_list.sort(key=lambda x: x[0])
                elif "Namespace" in sort_mode:
                    items_list.sort(key=lambda x: (
                        x[0].split(":", 1)[0] if ":" in x[0] else "minecraft",
                        x[0]
                    ))

                for item_id, data in items_list:
                    if isinstance(data, dict):
                        amt = int(math.ceil(data["amount"]))
                        inputs = data.get("inputs", {})
                        
                        action = "Craft"
                        m_lower = method.lower()
                        if "smelting" in m_lower or "furnace" in m_lower or "blasting" in m_lower:
                            action = "Smelt"
                        elif "crushing" in m_lower or "pulverizing" in m_lower or "grinding" in m_lower:
                            action = "Crush"

                        depth_tag = f" <font color='#7f8c8d'>[Step Lvl {depths.get(item_id, 0)}]</font>" if "Prerequisites First" in sort_mode else ""
                        recipe_count = len(self.resolver.recipes.get(item_id, []))
                        multi_badge = f" <font color='#e67e22' size='2'><b>[⚡ {recipe_count} Recipes]</b></font>" if recipe_count > 1 else ""
                        origin_badge = f" <font color='#e74c3c' size='2'><b>[⚠️ Origin Unknown]</b></font>" if self.resolver.is_self_referential(item_id) else ""
                        override_link = f" <a href='override:{item_id}' style='color:#e74c3c; font-size:11px; text-decoration:none;'>[🛑 Override Step]</a>"

                        html_blocks.append(
                            f"<div style='margin-top:6px;'><b>• {action} {amt}x <a href='item:{item_id}' style='color:#2980b9; text-decoration:none;'>{item_id}</a></b>{multi_badge}{origin_badge}{depth_tag}{override_link}</div>"
                        )

                        if inputs:
                            html_blocks.append("<div style='margin-left: 24px; margin-top:2px; margin-bottom:6px; color:#555;'>")
                            html_blocks.append("<i>↳ Inputs Required:</i><br/>")
                            for ing_id, q in inputs.items():
                                ing_qty = int(math.ceil(q))
                                ing_recipe_count = len(self.resolver.recipes.get(ing_id, []))
                                ing_badge = f" <font color='#e67e22' size='1'>[⚡ {ing_recipe_count} Recipes]</font>" if ing_recipe_count > 1 else ""
                                ing_origin = f" <font color='#e74c3c' size='1'>[⚠️ Origin Unknown]</font>" if self.resolver.is_self_referential(ing_id) else ""

                                tag_badge = ""
                                if ing_id.startswith("#"):
                                    if ing_id in self.resolver.material_replacements:
                                        replaced_with = self.resolver.material_replacements[ing_id]
                                        tag_badge = f" <font color='#27ae60' size='1'><b>[🏷️ Selected: {replaced_with}]</b></font>"
                                    else:
                                        matches = self.resolver.get_items_matching_tag(ing_id)
                                        if matches:
                                            tag_badge = f" <font color='#2980b9' size='1'><b>[🏷️ {len(matches)} Options Available]</b></font>"

                                html_blocks.append(
                                    f"&nbsp;&nbsp;&nbsp;&nbsp;• {ing_qty}x <a href='item:{ing_id}' style='color:#27ae60; text-decoration:none;'>{ing_id}</a>{ing_badge}{ing_origin}{tag_badge}<br/>"
                                )
                            html_blocks.append("</div>")
                    else:
                        amt = int(math.ceil(data))
                        override_link = f" <a href='override:{item_id}' style='color:#e74c3c; font-size:11px; text-decoration:none;'>[🛑 Override Step]</a>"
                        html_blocks.append(f"<div>• Process {amt}x <a href='item:{item_id}' style='color:#2980b9;'>{item_id}</a>{override_link}</div>")

        self.report_text.setHtml("".join(html_blocks))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = ModMaterialCalculatorGUI()
    gui.show()
    sys.exit(app.exec())