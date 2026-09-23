import os
import json
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ==================== RECIPE RESOLVER ENGINE ====================
class UniversalRecipeResolver:
    def __init__(self):
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

    def parse_json_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return

            recipe_type = data.get("type", "")
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
            elif "ae2:inscriber" in recipe_type or "inscriber" in file_path:
                for key in ["top", "middle", "bottom", "ingredients"]:
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
                    "inputs": dict(inputs)
                })

        except Exception:
            pass

    def scan_repository(self, repo_path):
        self.recipes.clear()
        for root, _, files in os.walk(repo_path):
            for file in files:
                if file.endswith(".json"):
                    self.parse_json_file(os.path.join(root, file))

    def get_raw_materials(self, item_id, target_amount=1.0, visited=None):
        item_id = self.normalize_id(item_id)
        if visited is None:
            visited = set()

        if item_id in self.raw_overrides or item_id not in self.recipes or item_id in visited:
            return {item_id: target_amount}

        visited.add(item_id)
        recipe = self.recipes[item_id][0]
        craft_yield = recipe["count"] if recipe["count"] > 0 else 1
        crafts_needed = target_amount / craft_yield
        
        raw_totals = defaultdict(float)
        for input_id, req_qty in recipe["inputs"].items():
            sub_totals = self.get_raw_materials(input_id, req_qty * crafts_needed, visited.copy())
            for raw_id, raw_qty in sub_totals.items():
                raw_totals[raw_id] += raw_qty

        return dict(raw_totals)


# ==================== TKINTER GUI CLASS ====================
class ModMaterialCalculatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Mod Material & Pattern Calculator")
        self.root.geometry("1000x700")

        self.db_file = "user_data.json"
        self.resolver = UniversalRecipeResolver()
        
        # Application state
        self.recent_repos = []
        self.current_repo = ""
        self.cart = {}  # {item_id: quantity}
        self.filtered_items = []

        self.load_user_data()
        self.setup_ui()

        # Auto-load last active repository if available
        if self.current_repo and os.path.exists(self.current_repo):
            self.load_repository(self.current_repo)

    def load_user_data(self):
        """Loads persistent JSON storage."""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r") as f:
                    data = json.load(f)
                    self.recent_repos = data.get("recent_repos", [])
                    self.current_repo = data.get("current_repo", "")
                    self.cart = data.get("cart", {})
                    self.resolver.raw_overrides = set(data.get("raw_overrides", [
                        "minecraft:iron_ingot", "minecraft:gold_ingot", "minecraft:redstone",
                        "minecraft:quartz", "ae2:certus_quartz_crystal", "ae2:silicon", "ae2:sky_stone_block"
                    ]))
            except Exception:
                pass

    def save_user_data(self):
        """Saves repository paths, shopping cart items, and quantities to JSON."""
        data = {
            "recent_repos": self.recent_repos[:10],
            "current_repo": self.current_repo,
            "cart": self.cart,
            "raw_overrides": list(self.resolver.raw_overrides)
        }
        with open(self.db_file, "w") as f:
            json.dump(data, f, indent=4)

    def setup_ui(self):
        # Top Frame: Repository Selector
        top_frame = ttk.LabelFrame(self.root, text=" Repository Settings ")
        top_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(top_frame, text="Recent Repos:").pack(side="left", padx=5)
        self.repo_combo = ttk.Combobox(top_frame, values=self.recent_repos, width=50)
        self.repo_combo.set(self.current_repo)
        self.repo_combo.pack(side="left", padx=5, fill="x", expand=True)

        ttk.Button(top_frame, text="Browse...", command=self.browse_repo).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Scan Repo", command=self.on_scan_click).pack(side="left", padx=5)

        # Paned Window: Left (Selection Area) / Right (Cart & Output)
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=5)

        # Left Column: Item Finder
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Search Patterns / Items:").pack(anchor="w")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.filter_items)
        search_entry = ttk.Entry(left_frame, textvariable=self.search_var)
        search_entry.pack(fill="x", pady=5)

        self.item_listbox = tk.Listbox(left_frame, selectmode="single")
        self.item_listbox.pack(fill="both", expand=True)

        add_frame = ttk.Frame(left_frame)
        add_frame.pack(fill="x", pady=5)

        ttk.Label(add_frame, text="Qty:").pack(side="left")
        self.qty_spinbox = ttk.Spinbox(add_frame, from_=1, to=1000, width=5)
        self.qty_spinbox.set(1)
        self.qty_spinbox.pack(side="left", padx=5)

        ttk.Button(add_frame, text="Add to Target Cart", command=self.add_selected_item).pack(side="right", fill="x", expand=True)

        # Right Column: Cart & Material Breakdown Results
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=2)

        # Cart Table
        cart_frame = ttk.LabelFrame(right_frame, text=" Selected Items / Quantities ")
        cart_frame.pack(fill="x", pady=5)

        self.cart_tree = ttk.Treeview(cart_frame, columns=("Item", "Qty"), show="headings", height=5)
        self.cart_tree.heading("Item", text="Item ID")
        self.cart_tree.heading("Qty", text="Quantity Needed")
        self.cart_tree.column("Qty", width=100, anchor="center")
        self.cart_tree.pack(fill="x", side="left", expand=True)

        cart_btn_frame = ttk.Frame(cart_frame)
        cart_btn_frame.pack(side="right", fill="y", padx=5)
        ttk.Button(cart_btn_frame, text="Remove", command=self.remove_cart_item).pack(fill="x", pady=2)
        ttk.Button(cart_btn_frame, text="Clear All", command=self.clear_cart).pack(fill="x", pady=2)

        # Calculate Button
        ttk.Button(right_frame, text="CALCULATE RAW MATERIALS", command=self.calculate_materials).pack(fill="x", pady=5)

        # Results Display Box
        result_frame = ttk.LabelFrame(right_frame, text=" Material Breakdown Report ")
        result_frame.pack(fill="both", expand=True)

        self.report_text = tk.Text(result_frame, wrap="word")
        scrollbar = ttk.Scrollbar(result_frame, command=self.report_text.yview)
        self.report_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.report_text.pack(fill="both", expand=True)

        self.refresh_cart_ui()

    def browse_repo(self):
        path = filedialog.askdirectory(title="Select Mod Repository Root Folder")
        if path:
            self.repo_combo.set(path)
            self.load_repository(path)

    def on_scan_click(self):
        path = self.repo_combo.get().strip()
        if os.path.exists(path):
            self.load_repository(path)
        else:
            messagebox.showerror("Error", "Directory path does not exist.")

    def load_repository(self, path):
        self.current_repo = path
        if path not in self.recent_repos:
            self.recent_repos.insert(0, path)
            self.repo_combo['values'] = self.recent_repos

        self.resolver.scan_repository(path)
        self.filter_items()
        self.save_user_data()

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
            messagebox.showwarning("Warning", "Add at least one item to your cart before calculating.")
            return

        self.report_text.delete("1.0", tk.END)
        grand_totals = defaultdict(float)

        self.report_text.insert(tk.END, "===================================================\n")
        self.report_text.insert(tk.END, "               INDIVIDUAL BREAKDOWNS\n")
        self.report_text.insert(tk.END, "===================================================\n\n")

        for item, qty in self.cart.items():
            self.report_text.insert(tk.END, f"--> Requirements for {qty}x [{item}]:\n")
            mats = self.resolver.get_raw_materials(item, target_amount=qty)
            for mat, amt in mats.items():
                self.report_text.insert(tk.END, f"      * {mat}: {round(amt, 2)}\n")
                grand_totals[mat] += amt
            self.report_text.insert(tk.END, "\n")

        self.report_text.insert(tk.END, "===================================================\n")
        self.report_text.insert(tk.END, "           COMBINED GRAND TOTAL MATERIALS\n")
        self.report_text.insert(tk.END, "===================================================\n\n")

        for mat, amt in grand_totals.items():
            stacks = amt / 64
            if stacks >= 1:
                stack_str = f"({int(stacks)} stacks + {round(amt % 64, 1)})"
            else:
                stack_str = ""
            self.report_text.insert(tk.END, f"  • {mat}: {round(amt, 2)} {stack_str}\n")


if __name__ == "__main__":
    root = tk.Tk()
    app = ModMaterialCalculatorGUI(root)
    root.mainloop()