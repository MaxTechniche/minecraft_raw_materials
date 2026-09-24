import os
import sys
import json
import math
import threading
from collections import defaultdict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QListWidget, QTreeWidget, QTreeWidgetItem, QTextEdit, QGroupBox,
    QSplitter, QScrollArea, QDialog, QFileDialog, QHeaderView
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont


# ==================== CROSS-PLATFORM PATH HELPER ====================
def get_user_data_filepath(filename="user_data.json"):
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
    except Exception:
        return filename


# ==================== ADVANCED RECIPE ENGINE ====================
class AdvancedRecipeResolver:
    def __init__(self):
        self.recipes = defaultdict(list)
        self.raw_overrides = set()
        self.item_caps = {}  
        self.material_replacements = {}  
        self.preferred_recipes = {}  
        self.all_known_items = set()  
        self.namespace_mappings = {}

    def standardize_path(self, path):
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

    def normalize_id(self, item_id):
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

        self.all_known_items.add(s_id)
        return s_id

    def normalize_tag(self, tag_str):
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
        self.all_known_items.add(final_tag)
        return final_tag

    def extract_ingredient_ids(self, obj):
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

    def categorize_method(self, recipe_type, file_path, tags):
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

    def unwrap_recipe_data(self, data):
        if not isinstance(data, dict):
            return None, ""
        for key, value in data.items():
            if "recipe" in key and isinstance(value, dict):
                return value, key
        return data, data.get("type", "")

    def parse_json_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

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
                self.recipes[result_id].append({
                    "count": result_count,
                    "inputs": dict(inputs),
                    "method": method
                })

        except Exception:
            pass

    def scan_repositories(self, repo_paths):
        self.recipes.clear()
        self.all_known_items.clear()
        for repo in repo_paths:
            if not os.path.exists(repo):
                continue
            for root, _, files in os.walk(repo):
                for file in files:
                    if file.endswith(".json"):
                        self.parse_json_file(os.path.join(root, file))

    def get_raw_materials(self, item_id, target_amount=1.0, visited=None, item_usage_tracker=None):
        item_id = self.normalize_id(item_id)
        target_amount = int(math.ceil(target_amount))
        
        if item_id in self.material_replacements:
            item_id = self.material_replacements[item_id]

        if visited is None:
            visited = set()
        if item_usage_tracker is None:
            item_usage_tracker = defaultdict(float)

        raw_totals = defaultdict(float)
        method_steps = defaultdict(lambda: defaultdict(lambda: {
            "amount": 0,
            "inputs": defaultdict(float)
        }))

        cap = self.item_caps.get(item_id, None)
        if cap is None and item_id in self.recipes:
            for r in self.recipes[item_id]:
                if any(self.normalize_id(inp) == item_id for inp in r["inputs"]):
                    cap = 1.0
                    break

        eff_target_amount = target_amount
        if cap is not None:
            already_used = item_usage_tracker[item_id]
            remaining_allowance = max(0.0, cap - already_used)
            eff_target_amount = min(target_amount, remaining_allowance)

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
                if not inputs_in_visited:
                    chosen_recipe = r

        if not chosen_recipe:
            for r in candidate_recipes:
                inputs_in_visited = any(self.normalize_id(inp) in visited for inp in r["inputs"] if self.normalize_id(inp) != item_id)
                if not inputs_in_visited:
                    chosen_recipe = r
                    break

        if not chosen_recipe:
            chosen_recipe = candidate_recipes[0]

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
                    norm_input_id, eff_req, visited.copy(), item_usage_tracker
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


# ==================== RECIPE VIEWER DIALOG ====================
class RecipeViewerDialog(QDialog):
    def __init__(self, parent, resolver, item_id, callback=None):
        super().__init__(parent)
        self.setWindowTitle(f"Recipe Viewer: {item_id}")
        self.resize(520, 500)
        self.resolver = resolver
        self.item_id = item_id
        self.callback = callback

        layout = QVBoxLayout(self)

        header = QLabel(f"Crafting Series for:\n{item_id}")
        header_font = QFont("Helvetica", 11, QFont.Bold)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll)

        self.populate_recipes()

        btn_layout = QHBoxLayout()
        clear_pref_btn = QPushButton("Clear Preference (Use Default)")
        clear_pref_btn.clicked.connect(self.clear_preference)
        btn_layout.addWidget(clear_pref_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def populate_recipes(self):
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        recipes = self.resolver.recipes.get(self.item_id, [])
        current_pref = self.resolver.preferred_recipes.get(self.item_id, None)

        if not recipes:
            no_recipe = QLabel("No recipe is defined for this item in the loaded repositories.\n\nIt is likely a base raw material, common tag component, or dropped from entities.")
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

            method_lbl = QLabel(f"<b>Method:</b> {recipe['method']}")
            box_layout.addWidget(method_lbl)

            yield_lbl = QLabel(f"<b>Yields:</b> {recipe['count']}x")
            box_layout.addWidget(yield_lbl)

            box_layout.addWidget(QLabel("<b>Ingredients Required:</b>"))
            for ing_id, ing_qty in recipe['inputs'].items():
                ing_lbl = QLabel(f"  • {ing_qty} x {ing_id}")
                box_layout.addWidget(ing_lbl)

            btn_hbox = QHBoxLayout()
            btn_hbox.addStretch()

            select_btn = QPushButton("★ Active Preference" if is_active else "Select as Preferred Recipe")
            select_btn.setEnabled(not is_active)
            select_btn.clicked.connect(lambda checked, idx=i: self.set_preferred_recipe(idx))
            btn_hbox.addWidget(select_btn)

            box_layout.addLayout(btn_hbox)
            self.scroll_layout.addWidget(box)

        self.scroll_layout.addStretch()

    def set_preferred_recipe(self, idx):
        self.resolver.preferred_recipes[self.item_id] = idx
        self.populate_recipes()
        if self.callback:
            self.callback()

    def clear_preference(self):
        if self.item_id in self.resolver.preferred_recipes:
            del self.resolver.preferred_recipes[self.item_id]
            self.populate_recipes()
            if self.callback:
                self.callback()


# ==================== MATERIAL REPLACEMENT DIALOG ====================
class MaterialReplacementDialog(QDialog):
    def __init__(self, parent, resolver, target_item, callback):
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

    def filter_items(self):
        query = self.search_entry.text().lower().strip()
        self.item_listwidget.clear()
        for item in sorted(list(self.resolver.all_known_items)):
            if not query or query in item.lower():
                self.item_listwidget.addItem(item)

    def on_select(self):
        items = self.item_listwidget.selectedItems()
        if items:
            self.selection_entry.setText(items[0].text())

    def apply_replacement(self):
        new_val = self.selection_entry.text().strip()
        if new_val:
            self.resolver.material_replacements[self.target_item] = new_val
        self.callback()
        self.accept()

    def clear_override(self):
        if self.target_item in self.resolver.material_replacements:
            del self.resolver.material_replacements[self.target_item]
        self.callback()
        self.accept()


# ==================== MAIN APPLICATION GUI ====================
class ModMaterialCalculatorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mod Material & Pattern Calculator")
        self.resize(1150, 800)

        self.db_file = get_user_data_filepath("user_data.json")
        self.resolver = AdvancedRecipeResolver()
        
        self.active_repos = []
        self.cart = {}
        self.signals = WorkerSignals()

        self._cached_raw_totals = {}
        self._cached_method_totals = {}

        self.signals.rescan_done.connect(self._on_rescan_complete)
        self.signals.calc_done.connect(self._on_calculation_finished)

        self.load_user_data()
        self.setup_ui()

        if self.active_repos:
            self.rescan_all_repos()

    def load_user_data(self):
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
                    self.resolver.raw_overrides = set(data.get("raw_overrides", [
                        "minecraft:iron_ingot", "minecraft:gold_ingot", "minecraft:redstone",
                        "minecraft:copper_ingot", "minecraft:quartz", "minecraft:stick",
                        "ae2:certus_quartz_crystal", "ae2:silicon", "ae2:sky_stone_block"
                    ]))
            except Exception:
                pass

    def save_user_data(self):
        data = {
            "active_repos": self.active_repos,
            "cart": self.cart,
            "namespace_mappings": self.resolver.namespace_mappings,
            "preferred_recipes": self.resolver.preferred_recipes,
            "item_caps": self.resolver.item_caps,
            "material_replacements": self.resolver.material_replacements,
            "raw_overrides": list(self.resolver.raw_overrides)
        }
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def setup_ui(self):
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

        top_layout.addStretch()
        root_layout.addWidget(top_group)

        # Main Splitter
        main_splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(main_splitter, stretch=1)

        # Left Column Panel
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("Search Patterns / Products:"))

        self.search_entry = QLineEdit()
        self.search_entry.textChanged.connect(self.filter_items)
        left_layout.addWidget(self.search_entry)

        self.item_listwidget = QListWidget()
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

        # Cart Box
        cart_group = QGroupBox(" Selected Items Cart ")
        cart_layout = QVBoxLayout(cart_group)

        self.cart_tree = QTreeWidget()
        self.cart_tree.setHeaderLabels(["Item ID", "Quantity Needed"])
        self.cart_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cart_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
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

        right_layout.addWidget(cart_group)

        self.status_label = QLabel("Ready.")
        status_font = QFont("Helvetica", 9, QFont.Normal)
        status_font.setItalic(True)
        self.status_label.setFont(status_font)
        right_layout.addWidget(self.status_label)

        # Material Breakdown Group
        report_group = QGroupBox(" Material Breakdown Report ")
        report_layout = QVBoxLayout(report_group)

        report_splitter = QSplitter(Qt.Vertical)

        # Raw Materials Section with Sort Controls
        raw_widget = QWidget()
        raw_layout = QVBoxLayout(raw_widget)
        raw_layout.setContentsMargins(0, 0, 0, 0)

        raw_header_layout = QHBoxLayout()
        raw_header_layout.addWidget(QLabel("Raw Materials Required (Double-Click to Replace/Override):"))
        raw_header_layout.addStretch()

        raw_header_layout.addWidget(QLabel("Sort Materials By:"))
        self.raw_sort_combo = QComboBox()
        self.raw_sort_combo.addItems([
            "Highest Quantity First",
            "Lowest Quantity First",
            "Alphabetical (A-Z)",
            "Tags First (Grouped)"
        ])
        self.raw_sort_combo.currentIndexChanged.connect(self.refresh_raw_materials_display)
        raw_header_layout.addWidget(self.raw_sort_combo)

        raw_layout.addLayout(raw_header_layout)

        self.report_tree = QTreeWidget()
        self.report_tree.setHeaderLabels(["Raw Material / Tag", "Quantity Needed"])
        self.report_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.report_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.report_tree.itemDoubleClicked.connect(self.open_replacement_dialog)
        raw_layout.addWidget(self.report_tree)

        report_splitter.addWidget(raw_widget)

        # Crafting Breakdown Section with Sort Controls
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)

        sort_header_layout = QHBoxLayout()
        sort_header_layout.addWidget(QLabel("Processing / Crafting Methods Breakdown:"))
        sort_header_layout.addStretch()

        sort_header_layout.addWidget(QLabel("Sort Steps By:"))
        self.craft_sort_combo = QComboBox()
        self.craft_sort_combo.addItems([
            "Prerequisites First (Dependency Order)",
            "Highest Quantity First",
            "Lowest Quantity First",
            "Alphabetical (A-Z)"
        ])
        self.craft_sort_combo.currentIndexChanged.connect(self.refresh_breakdown_display)
        sort_header_layout.addWidget(self.craft_sort_combo)

        text_layout.addLayout(sort_header_layout)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        text_layout.addWidget(self.report_text)

        report_splitter.addWidget(text_widget)
        report_splitter.setStretchFactor(0, 3)
        report_splitter.setStretchFactor(1, 2)

        report_layout.addWidget(report_splitter)
        right_layout.addWidget(report_group, stretch=1)

        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)

        self.refresh_cart_ui()
        self.trigger_async_calculation()

    def open_replacement_dialog(self, item, column):
        display_name = item.text(0)
        item_id = display_name.replace("[Tag] ", "")
        MaterialReplacementDialog(self, self.resolver, item_id, self.trigger_async_calculation).exec()

    def open_repo_manager(self):
        path = QFileDialog.getExistingDirectory(self, "Select Mod Repository Folder")
        if path and path not in self.active_repos:
            self.active_repos.append(path)
            self.repo_label.setText(f"Active Repositories: {len(self.active_repos)}")
            self.rescan_all_repos()
            self.save_user_data()

    def rescan_all_repos(self):
        self.status_label.setText("Scanning repositories...")
        threading.Thread(target=self._rescan_thread, daemon=True).start()

    def _rescan_thread(self):
        self.resolver.scan_repositories(self.active_repos)
        self.signals.rescan_done.emit()

    def _on_rescan_complete(self):
        self.filter_items()
        self.status_label.setText("Scanning complete.")
        self.trigger_async_calculation()

    def filter_items(self):
        query = self.search_entry.text().lower().strip()
        self.item_listwidget.clear()
        all_items = sorted(list(self.resolver.recipes.keys()))

        if not all_items:
            self.item_listwidget.addItem("[ No Repositories Loaded - Click 'Manage Repos...' above ]")
            return

        for item in all_items:
            if query in item.lower():
                self.item_listwidget.addItem(item)

    def add_selected_item(self):
        items = self.item_listwidget.selectedItems()
        if not items:
            return
        item_id = items[0].text()
        if item_id.startswith("["):
            return

        qty = self.qty_spinbox.value()
        self.cart[item_id] = self.cart.get(item_id, 0) + qty
        self.refresh_cart_ui()
        self.save_user_data()
        self.trigger_async_calculation()

    def remove_cart_item(self):
        selected = self.cart_tree.selectedItems()
        if not selected:
            return
        item_id = selected[0].text(0)
        if item_id in self.cart:
            del self.cart[item_id]
            self.refresh_cart_ui()
            self.save_user_data()
            self.trigger_async_calculation()

    def clear_cart(self):
        self.cart.clear()
        self.refresh_cart_ui()
        self.save_user_data()
        self.trigger_async_calculation()

    def refresh_cart_ui(self):
        self.cart_tree.clear()
        for item_id, qty in self.cart.items():
            tree_item = QTreeWidgetItem([item_id, str(qty)])
            self.cart_tree.addTopLevelItem(tree_item)

    def trigger_async_calculation(self):
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

        self.status_label.setText("Calculating raw materials in background...")
        threading.Thread(target=self._async_calculate_worker, daemon=True).start()

    def _async_calculate_worker(self):
        grand_raw_totals = defaultdict(float)
        grand_method_totals = defaultdict(lambda: defaultdict(lambda: {
            "amount": 0,
            "inputs": defaultdict(float)
        }))

        item_usage_tracker = defaultdict(float)

        for item, qty in list(self.cart.items()):
            raw_mats, methods = self.resolver.get_raw_materials(item, target_amount=qty, item_usage_tracker=item_usage_tracker)
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

    def _on_calculation_finished(self, grand_raw_totals, grand_method_totals):
        self._cached_raw_totals = grand_raw_totals
        self._cached_method_totals = grand_method_totals
        
        # Populate raw material tree and crafting text
        self.refresh_raw_materials_display()
        self.refresh_breakdown_display()
        self.status_label.setText("Calculation up to date.")

    def refresh_raw_materials_display(self):
        """Re-sorts and populates the raw materials tree with integer quantities."""
        if not self._cached_raw_totals:
            return

        self.report_tree.clear()
        sort_mode = self.raw_sort_combo.currentText()

        raw_list = list(self._cached_raw_totals.items())

        if "Highest Quantity" in sort_mode:
            raw_list.sort(key=lambda x: x[1], reverse=True)
        elif "Lowest Quantity" in sort_mode:
            raw_list.sort(key=lambda x: x[1])
        elif "Alphabetical" in sort_mode:
            raw_list.sort(key=lambda x: x[0])
        elif "Tags First" in sort_mode:
            raw_list.sort(key=lambda x: (not x[0].startswith("#"), -x[1]))

        for mat, amt in raw_list:
            amt_int = int(math.ceil(amt))
            stacks = amt_int // 64
            rem_items = amt_int % 64

            if stacks >= 1:
                stack_str = f" ({stacks} stacks + {rem_items})" if rem_items > 0 else f" ({stacks} stacks)"
            else:
                stack_str = ""

            prefix = "[Tag] " if mat.startswith("#") else ""
            display_name = f"{prefix}{mat}"
            display_qty = f"{amt_int}{stack_str}"
            self.report_tree.addTopLevelItem(QTreeWidgetItem([display_name, display_qty]))

    def _calculate_dependency_depths(self, grand_method_totals):
        """Calculates crafting tree depth (0 = prerequisite craft, higher = depends on prior crafts)."""
        craft_items = set()
        item_inputs = defaultdict(set)

        for method, items_dict in grand_method_totals.items():
            for item_id, data in items_dict.items():
                craft_items.add(item_id)
                if isinstance(data, dict):
                    for inp_id in data.get("inputs", {}).keys():
                        item_inputs[item_id].add(inp_id)

        depths = {}

        def get_depth(item_id, visited=None):
            if visited is None:
                visited = set()
            if item_id in depths:
                return depths[item_id]
            if item_id in visited:
                return 0
            visited.add(item_id)

            max_input_depth = -1
            for inp_id in item_inputs[item_id]:
                if inp_id in craft_items:
                    max_input_depth = max(max_input_depth, get_depth(inp_id, visited.copy()))

            depths[item_id] = max_input_depth + 1
            return depths[item_id]

        for item_id in craft_items:
            get_depth(item_id)

        return depths

    def refresh_breakdown_display(self):
        """Re-sorts and renders crafting steps with whole-number amounts."""
        if not self._cached_method_totals:
            return

        sort_mode = self.craft_sort_combo.currentText()
        depths = self._calculate_dependency_depths(self._cached_method_totals)

        lines = []
        for method, items_dict in self._cached_method_totals.items():
            lines.append(f"=== [ Method: {method} ] ===")

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

            for item_id, data in items_list:
                if isinstance(data, dict):
                    amt = int(math.ceil(data["amount"]))
                    inputs = data.get("inputs", {})
                    p_str = ", ".join([f"{int(math.ceil(q))}x {ing}" for ing, q in inputs.items()])
                    
                    action = "Craft"
                    m_lower = method.lower()
                    if "smelting" in m_lower or "furnace" in m_lower or "blasting" in m_lower:
                        action = "Smelt"
                    elif "crushing" in m_lower or "pulverizing" in m_lower or "grinding" in m_lower:
                        action = "Crush"

                    depth_tag = f" [Step Lvl {depths.get(item_id, 0)}]" if "Prerequisites First" in sort_mode else ""

                    if p_str:
                        lines.append(f"   - {action} {amt}x {item_id}{depth_tag} (using {p_str})")
                    else:
                        lines.append(f"   - {action} {amt}x {item_id}{depth_tag}")
                else:
                    lines.append(f"   - Process {int(math.ceil(data))}x {item_id}")
            lines.append("")

        self.report_text.setText("\n".join(lines))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = ModMaterialCalculatorGUI()
    gui.show()
    sys.exit(app.exec())