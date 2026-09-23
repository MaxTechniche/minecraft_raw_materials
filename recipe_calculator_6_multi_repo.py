import os
import json
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ==================== ADVANCED RECIPE ENGINE ====================
class AdvancedRecipeResolver:
    def __init__(self):
        # Maps item_id -> list of recipes
        self.recipes = defaultdict(list)
        self.raw_overrides = set()

    def normalize_id(self, item_id):
        if isinstance(item_id, dict):
            if "item" in item_id:
                return self.normalize_id(item_id["item"])
            elif "tag" in item_id:
                return f"#{item_id['tag']}"
            elif "id" in item_id:
                return self.normalize_id(item_id["id"])
            return ""
        if isinstance(item_id, list) and len(item_id) > 0:
            return self.normalize_id(item_id[0])
        
        s_id = str(item_id).strip()
        if not s_id.startswith("minecraft:") and ":" not in s_id and not s_id.startswith("#"):
            return f"minecraft:{s_id}"
        return s_id

    def extract_ingredient_ids(self, obj):
        found = []
        if isinstance(obj, dict):
            if "item" in obj or "tag" in obj or "id" in obj:
                found.append(self.normalize_id(obj))
            else:
                for v in obj.values():
                    found.extend(self.extract_ingredient_ids(v))
        elif isinstance(obj, list):
            for item in obj:
                found.extend(self.extract_ingredient_ids(item))
        elif isinstance(obj, str):
            found.append(self.normalize_id(obj))
        return [f for f in found if f]

    def categorize_method(self, recipe_type, file_path):
        """Classifies the processing/crafting method for grouping in reports."""
        r_type = recipe_type.lower()
        f_path = file_path.lower()

        if "smelting" in r_type or "smelting" in f_path or "furnace" in f_path:
            return "Smelting / Furnace"
        elif "blasting" in r_type or "blasting" in f_path:
            return "Blasting / Blast Furnace"
        elif "crushing" in r_type or "pulverizing" in r_type or "grinding" in r_type or "crusher" in f_path:
            return "Crushing / Pulverizing"
        elif "inscriber" in r_type or "inscriber" in f_path:
            return "Inscriber Processing (AE2)"
        elif "transform" in r_type or "transform" in f_path or "charger" in r_type:
            return "In-World / Energy Transformation"
        elif "smithing" in r_type:
            return "Smithing Table"
        else:
            return "Crafting Table"

    def parse_json_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return

            recipe_type = data.get("type", "")
            method = self.categorize_method(recipe_type, file_path)
            
            result_id = None
            result_count = 1

            # Determine Result Output
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

            if not result_id:
                return

            inputs = defaultdict(int)

            # 1. Shaped Crafting
            if "pattern" in data and "key" in data:
                key_map = data["key"]
                pattern = data["pattern"]
                for row in pattern:
                    for char in row:
                        if char != " " and char in key_map:
                            for ing in self.extract_ingredient_ids(key_map[char]):
                                inputs[ing] += 1
                                break

            # 2. Inscriber Processing (AE2)
            elif "ae2:inscriber" in recipe_type or "inscriber" in file_path:
                for key in ["top", "middle", "bottom", "ingredients"]:
                    if key in data:
                        for ing in self.extract_ingredient_ids(data[key]):
                            inputs[ing] += 1

            # 3. AE2 Transform / Charger / World Crafting
            elif "ae2:transform" in recipe_type or "transform" in file_path:
                for key in ["ingredients", "from"]:
                    if key in data:
                        for ing in self.extract_ingredient_ids(data[key]):
                            inputs[ing] += 1

            # 4. Furnace, Blasting, Smelting, Crushing, & Generic Ingredients
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
        for repo in repo_paths:
            if not os.path.exists(repo):
                continue
            for root, _, files in os.walk(repo):
                for file in files:
                    if file.endswith(".json"):
                        self.parse_json_file(os.path.join(root, file))

    def get_raw_materials(self, item_id, target_amount=1.0, visited=None):
        """Recursively gets raw totals and organizes step operations by method."""
        item_id = self.normalize_id(item_id)
        if visited is None:
            visited = set()

        if item_id in self.raw_overrides or item_id not in self.recipes or item_id in visited:
            return {item_id: target_amount}, defaultdict(lambda: defaultdict(float))

        visited.add(item_id)
        recipe = self.recipes[item_id][0]
        craft_yield = recipe["count"] if recipe["count"] > 0 else 1
        crafts_needed = target_amount / craft_yield
        method = recipe["method"]

        raw_totals = defaultdict(float)
        method_steps = defaultdict(lambda: defaultdict(float))

        # Record this item's crafting method
        method_steps[method][item_id] += target_amount

        for input_id, req_qty in recipe["inputs"].items():
            sub_raw, sub_methods = self.get_raw_materials(input_id, req_qty * crafts_needed, visited.copy())
            
            for r_id, r_qty in sub_raw.items():
                raw_totals[r_id] += r_qty
            for m_type, items in sub_methods.items():
                for sub_item, sub_qty in items.items():
                    method_steps[m_type][sub_item] += sub_qty

        return dict(raw_totals), method_steps


# ==================== TKINTER MULTI-REPO DIALOG ====================
class RepoManagerDialog(tk.Toplevel):
    def __init__(self, parent, repos_list):
        super().__init__(parent)
        self.title("Manage Repository Folders")
        self.geometry("600x400")
        self.repos = list(repos_list)
        self.result = None

        ttk.Label(self, text="Active Mod Repository Sources:").pack(anchor="w", padx=10, pady=5)

        # Listbox with Scrollbar
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.repo_listbox = tk.Listbox(frame)
        scrollbar = ttk.Scrollbar(frame, command=self.repo_listbox.yview)
        self.repo_listbox.configure(yscrollcommand=scrollbar.set)
        self.repo_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.refresh_list()

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(btn_frame, text="Add Repo Directory...", command=self.add_repo).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_repo).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Save & Scan", command=self.save_and_close).pack(side="right", padx=5)

    def refresh_list(self):
        self.repo_listbox.delete(0, tk.END)
        for r in self.repos:
            self.repo_listbox.insert(tk.END, r)

    def add_repo(self):
        path = filedialog.askdirectory(title="Select Mod Repository Folder")
        if path and path not in self.repos:
            self.repos.append(path)
            self.refresh_list()

    def remove_repo(self):
        sel = self.repo_listbox.curselection()
        if sel:
            del self.repos[sel[0]]
            self.refresh_list()

    def save_and_close(self):
        self.result = self.repos
        self.destroy()


# ==================== MAIN APPLICATION GUI ====================
class ModMaterialCalculatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Mod Material & Recipe Calculator")
        self.root.geometry("1100x750")

        self.db_file = "user_data.json"
        self.resolver = AdvancedRecipeResolver()
        
        # State Data
        self.active_repos = []
        self.cart = {}
        self.filtered_items = []

        self.load_user_data()
        self.setup_ui()

        if self.active_repos:
            self.rescan_all_repos()

    def load_user_data(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r") as f:
                    data = json.load(f)
                    self.active_repos = data.get("active_repos", [])
                    self.cart = data.get("cart", {})
                    self.resolver.raw_overrides = set(data.get("raw_overrides", [
                        "minecraft:iron_ingot", "minecraft:gold_ingot", "minecraft:redstone",
                        "minecraft:copper_ingot", "minecraft:quartz", "ae2:certus_quartz_crystal",
                        "ae2:silicon", "ae2:sky_stone_block"
                    ]))
            except Exception:
                pass

    def save_user_data(self):
        data = {
            "active_repos": self.active_repos,
            "cart": self.cart,
            "raw_overrides": list(self.resolver.raw_overrides)
        }
        with open(self.db_file, "w") as f:
            json.dump(data, f, indent=4)

    def setup_ui(self):
        # Top Bar: Multi-Repo Management
        top_frame = ttk.LabelFrame(self.root, text=" Repository Management ")
        top_frame.pack(fill="x", padx=10, pady=5)

        self.repo_label = ttk.Label(top_frame, text=f"Active Repositories: {len(self.active_repos)}")
        self.repo_label.pack(side="left", padx=10)

        ttk.Button(top_frame, text="Manage Repos...", command=self.open_repo_manager).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Rescan Repositories", command=self.rescan_all_repos).pack(side="left", padx=5)

        # Paned Window Split View
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=5)

        # Left Column: Item Search (Scrollable)
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Search Patterns / Products:").pack(anchor="w")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.filter_items)
        ttk.Entry(left_frame, textvariable=self.search_var).pack(fill="x", pady=5)

        list_scroll_frame = ttk.Frame(left_frame)
        list_scroll_frame.pack(fill="both", expand=True)

        self.item_listbox = tk.Listbox(list_scroll_frame)
        lb_scrollbar = ttk.Scrollbar(list_scroll_frame, command=self.item_listbox.yview)
        self.item_listbox.configure(yscrollcommand=lb_scrollbar.set)
        
        self.item_listbox.pack(side="left", fill="both", expand=True)
        lb_scrollbar.pack(side="right", fill="y")

        add_frame = ttk.Frame(left_frame)
        add_frame.pack(fill="x", pady=5)

        ttk.Label(add_frame, text="Qty:").pack(side="left")
        self.qty_spinbox = ttk.Spinbox(add_frame, from_=1, to=10000, width=6)
        self.qty_spinbox.set(1)
        self.qty_spinbox.pack(side="left", padx=5)

        ttk.Button(add_frame, text="Add to Cart", command=self.add_selected_item).pack(side="right", fill="x", expand=True)

        # Right Column: Cart & Scrollable Report
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=2)

        # Cart Table (Scrollable Treeview)
        cart_frame = ttk.LabelFrame(right_frame, text=" Selected Items Cart ")
        cart_frame.pack(fill="x", pady=5)

        cart_tree_frame = ttk.Frame(cart_frame)
        cart_tree_frame.pack(fill="x", expand=True)

        self.cart_tree = ttk.Treeview(cart_tree_frame, columns=("Item", "Qty"), show="headings", height=5)
        self.cart_tree.heading("Item", text="Item ID")
        self.cart_tree.heading("Qty", text="Quantity Needed")
        self.cart_tree.column("Qty", width=120, anchor="center")

        cart_scroll = ttk.Scrollbar(cart_tree_frame, command=self.cart_tree.yview)
        self.cart_tree.configure(yscrollcommand=cart_scroll.set)

        self.cart_tree.pack(side="left", fill="x", expand=True)
        cart_scroll.pack(side="right", fill="y")

        cart_btn_frame = ttk.Frame(cart_frame)
        cart_btn_frame.pack(fill="x", pady=5)
        ttk.Button(cart_btn_frame, text="Remove Selected", command=self.remove_cart_item).pack(side="left", padx=5)
        ttk.Button(cart_btn_frame, text="Clear Cart", command=self.clear_cart).pack(side="left", padx=5)

        # Action Button
        ttk.Button(right_frame, text="CALCULATE MATERIAL BREAKDOWN", command=self.calculate_materials).pack(fill="x", pady=5)

        # Report Area (Scrollable Text)
        result_frame = ttk.LabelFrame(right_frame, text=" Material Breakdown & Method Analysis ")
        result_frame.pack(fill="both", expand=True)

        self.report_text = tk.Text(result_frame, wrap="word")
        text_scroll = ttk.Scrollbar(result_frame, command=self.report_text.yview)
        self.report_text.configure(yscrollcommand=text_scroll.set)

        self.report_text.pack(side="left", fill="both", expand=True)
        text_scroll.pack(side="right", fill="y")

        self.refresh_cart_ui()

    def open_repo_manager(self):
        dlg = RepoManagerDialog(self.root, self.active_repos)
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.active_repos = dlg.result
            self.repo_label.config(text=f"Active Repositories: {len(self.active_repos)}")
            self.rescan_all_repos()
            self.save_user_data()

    def rescan_all_repos(self):
        self.resolver.scan_repositories(self.active_repos)
        self.filter_items()

    def filter_items(self, *args):
        query = self.search_var.get().lower().strip()
        self.item_listbox.delete(0, tk.END)
        all_items = sorted(list(self.resolver.recipes.keys()))

        self.filtered_items = [item for item in all_items if query in item.lower()]
        for item in self.filtered_items:
            self.item_listbox.insert(tk.END, item)

    def add_selected_item(self):
        sel = self.item_listbox.curselection()
        if not sel:
            return
        item = self.filtered_items[sel[0]]
        try:
            qty = int(self.qty_spinbox.get())
        except ValueError:
            qty = 1

        self.cart[item] = self.cart.get(item, 0) + qty
        self.refresh_cart_ui()
        self.save_user_data()

    def remove_cart_item(self):
        selected = self.cart_tree.selection()
        if not selected:
            return
        item_id = self.cart_tree.item(selected[0])['values'][0]
        if item_id in self.cart:
            del self.cart[item_id]
            self.refresh_cart_ui()
            self.save_user_data()

    def clear_cart(self):
        self.cart.clear()
        self.refresh_cart_ui()
        self.save_user_data()

    def refresh_cart_ui(self):
        for row in self.cart_tree.get_children():
            self.cart_tree.delete(row)
        for item, qty in self.cart.items():
            self.cart_tree.insert("", "end", values=(item, qty))

    def calculate_materials(self):
        if not self.cart:
            messagebox.showwarning("Warning", "Cart is empty!")
            return

        self.report_text.delete("1.0", tk.END)
        grand_raw_totals = defaultdict(float)
        grand_method_totals = defaultdict(lambda: defaultdict(float))

        for item, qty in self.cart.items():
            raw_mats, methods = self.resolver.get_raw_materials(item, target_amount=qty)
            for r_id, r_qty in raw_mats.items():
                grand_raw_totals[r_id] += r_qty
            for m_type, items in methods.items():
                for sub_item, sub_qty in items.items():
                    grand_method_totals[m_type][sub_item] += sub_qty

        # SECTION 1: Grand Raw Material Totals (Sorted by Quantity Descending)
        self.report_text.insert(tk.END, "===================================================\n")
        self.report_text.insert(tk.END, "  TOTAL RAW MATERIALS NEEDED (SORTED BY QUANTITY)\n")
        self.report_text.insert(tk.END, "===================================================\n\n")

        # Sort descending by required amount
        sorted_raw = sorted(grand_raw_totals.items(), key=lambda x: x[1], reverse=True)

        for mat, amt in sorted_raw:
            stacks = amt / 64
            stack_str = f" ({int(stacks)} stacks + {round(amt % 64, 1)})" if stacks >= 1 else ""
            self.report_text.insert(tk.END, f"  • {mat}: {round(amt, 2)}{stack_str}\n")

        # SECTION 2: Grouped by Production / Crafting Method
        self.report_text.insert(tk.END, "\n===================================================\n")
        self.report_text.insert(tk.END, "     BREAKDOWN BY CRAFTING / PROCESSING METHOD\n")
        self.report_text.insert(tk.END, "===================================================\n\n")

        for method, items_dict in grand_method_totals.items():
            self.report_text.insert(tk.END, f"=== [ Method: {method} ] ===\n")
            # Sort items in this method descending by quantity
            sorted_method_items = sorted(items_dict.items(), key=lambda x: x[1], reverse=True)
            for item_id, item_qty in sorted_method_items:
                self.report_text.insert(tk.END, f"   - {item_id}: {round(item_qty, 2)}\n")
            self.report_text.insert(tk.END, "\n")


if __name__ == "__main__":
    root = tk.Tk()
    app = ModMaterialCalculatorGUI(root)
    root.mainloop()