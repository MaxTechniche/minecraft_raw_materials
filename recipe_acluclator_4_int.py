import os
import json
from collections import defaultdict
from typing import Dict, Any, List, Set

class UniversalRecipeResolver:
    def __init__(self, repo_root_path: str):
        self.repo_root = repo_root_path
        self.recipes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.raw_overrides: Set[str] = set()

    def normalize_id(self, item_id: Any) -> str:
        """Normalizes item IDs across tags, strings, and dictionary definitions."""
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

    def extract_ingredient_ids(self, obj: Any) -> List[str]:
        """Deep searches any object/list structure for ingredient item references."""
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

    def parse_json_file(self, file_path: str):
        """Attempts to parse any JSON file in the repo to see if it acts as a recipe."""
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

            # 1. Shaped crafting patterns
            if "pattern" in data and "key" in data:
                key_map = data["key"]
                pattern = data["pattern"]
                for row in pattern:
                    for char in row:
                        if char != " " and char in key_map:
                            for ing in self.extract_ingredient_ids(key_map[char]):
                                inputs[ing] += 1
                                break

            # 2. Inscriber / Custom Machine processing
            elif "ae2:inscriber" in recipe_type or "inscriber" in file_path:
                for key in ["top", "middle", "bottom", "ingredients"]:
                    if key in data:
                        for ing in self.extract_ingredient_ids(data[key]):
                            inputs[ing] += 1

            # 3. Standard ingredients array / object
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
                    "source": os.path.basename(file_path)
                })

        except Exception:
            pass

    def scan_repository(self):
        """Walks the entire repository directory tree looking for JSON files."""
        for root, _, files in os.walk(self.repo_root):
            for file in files:
                if file.endswith(".json"):
                    full_path = os.path.join(root, file)
                    self.parse_json_file(full_path)

    def get_raw_materials(self, item_id: str, target_amount: float = 1.0, visited=None) -> Dict[str, float]:
        """Recursively resolves intermediate components into raw base items."""
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


# ==================== INTERACTIVE CLI ====================
def run_interactive_cli(repo_path: str):
    resolver = UniversalRecipeResolver(repo_root_path=repo_path)

    # Base items that shouldn't be broken down further
    resolver.raw_overrides = {
        "minecraft:iron_ingot",
        "minecraft:gold_ingot",
        "minecraft:redstone",
        "minecraft:copper_ingot",
        "minecraft:quartz",
        "minecraft:diamond",
        "minecraft:glowstone_dust",
        "minecraft:glass",
        "ae2:certus_quartz_crystal",
        "ae2:silicon",
        "ae2:sky_stone_block",
        "ae2:fluix_crystal"
    }

    print(f"Scanning '{repo_path}' for recipes...")
    resolver.scan_repository()
    
    all_items = sorted(list(resolver.recipes.keys()))
    if not all_items:
        print("No recipes found! Check the repository path.")
        return

    print(f"Loaded {len(all_items)} craftable items.\n")

    selected_items: Dict[str, int] = {}

    while True:
        print("\n" + "="*50)
        print("      APPLIED ENERGISTICS 2 / MOD MATERIAL CALCULATOR")
        print("="*50)
        print("Cart items:")
        if not selected_items:
            print("  (Empty)")
        else:
            for item, qty in selected_items.items():
                print(f"  - {item} x{qty}")

        print("\nOptions:")
        print("  1. Search and add items to target list")
        print("  2. Calculate required materials")
        print("  3. Clear cart")
        print("  4. Exit")
        
        choice = input("\nSelect an option (1-4): ").strip()

        if choice == "1":
            search_query = input("\nEnter item name or keyword to search (e.g., 'cell', 'drive'): ").strip().lower()
            matches = [item for item in all_items if search_query in item.lower()]

            if not matches:
                print("No items matched your search.")
                continue

            print(f"\nMatches found ({len(matches)}):")
            for idx, match in enumerate(matches, 1):
                print(f"  [{idx}] {match}")

            item_idx = input("\nEnter index number to select item (or press Enter to cancel): ").strip()
            if not item_idx.isdigit():
                continue

            idx_num = int(item_idx)
            if 1 <= idx_num <= len(matches):
                chosen_item = matches[idx_num - 1]
                qty_str = input(f"How many [{chosen_item}] do you need? ").strip()
                qty = int(qty_str) if qty_str.isdigit() else 1
                selected_items[chosen_item] = selected_items.get(chosen_item, 0) + qty
                print(f"Added {qty}x [{chosen_item}] to your list.")
            else:
                print("Invalid index choice.")

        elif choice == "2":
            if not selected_items:
                print("Your cart is empty! Add items before calculating.")
                continue

            print("\n" + "="*60)
            print("                MATERIAL BREAKDOWN REPORT")
            print("="*60)

            grand_totals = defaultdict(float)

            # Per-Item Breakdown
            for item, qty in selected_items.items():
                print(f"\n>>> Requirements for {qty}x [{item}]:")
                mats = resolver.get_raw_materials(item, target_amount=qty)
                for mat, amt in mats.items():
                    print(f"    - {mat}: {round(amt, 2)}")
                    grand_totals[mat] += amt

            # Combined Grand Totals
            print("\n" + "-"*60)
            print(">>> GRAND TOTAL COMBINED RAW MATERIALS NEEDED:")
            print("-"*60)
            for mat, amt in grand_totals.items():
                # Display stack count (64 per stack) alongside total
                stacks = amt / 64
                if stacks >= 1:
                    print(f"  * {mat}: {round(amt, 2)}  ({int(stacks)} stacks + {round(amt % 64, 1)})")
                else:
                    print(f"  * {mat}: {round(amt, 2)}")

            input("\nPress Enter to return to menu...")

        elif choice == "3":
            selected_items.clear()
            print("Cart cleared.")

        elif choice == "4":
            print("Exiting calculator.")
            break

if __name__ == "__main__":
    # Point to your local repo path
    REPO_PATH = "Applied-Energistics-2-main"
    run_interactive_cli(REPO_PATH)