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

            # Recipe JSONs usually have a 'type' field or a 'result' definition
            recipe_type = data.get("type", "")
            
            # Find the result item and yield count
            result_id = None
            result_count = 1

            if "result" in data:
                res = data["result"]
                if isinstance(res, str):
                    result_id = self.normalize_id(res)
                elif isinstance(res, dict):
                    result_id = self.normalize_id(res)
                    result_count = res.get("count", res.get("components", {}).get("count", 1))
            elif "output" in data: # AE2 / custom machine formats
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

            # 2. Inscriber / Custom Machine processing (AE2 specific keys)
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
            # Skip unparseable files or non-recipe JSONs silently
            pass

    def scan_repository(self):
        """Walks the ENTIRE repository directory tree looking for JSON files."""
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
        
        # Select first matching recipe found
        recipe = self.recipes[item_id][0]
        craft_yield = recipe["count"] if recipe["count"] > 0 else 1
        crafts_needed = target_amount / craft_yield
        
        raw_totals = defaultdict(float)

        for input_id, req_qty in recipe["inputs"].items():
            sub_totals = self.get_raw_materials(input_id, req_qty * crafts_needed, visited.copy())
            for raw_id, raw_qty in sub_totals.items():
                raw_totals[raw_id] += raw_qty

        return dict(raw_totals)


# ==================== USAGE EXAMPLE ====================
if __name__ == "__main__":
    # Point this directly to the root folder of ANY cloned repository
    REPO_ROOT_DIR = "Applied-Energistics-2-main"

    resolver = UniversalRecipeResolver(repo_root_path=REPO_ROOT_DIR)

    # Base items you want to stop breaking down at
    resolver.raw_overrides = {
        "minecraft:iron_ingot",
        "minecraft:gold_ingot",
        "minecraft:redstone",
        "minecraft:copper_ingot",
        "minecraft:quartz",
        "ae2:certus_quartz_crystal",
        "ae2:silicon",
        "ae2:sky_stone_block"
    }

    print(f"Scanning repository '{REPO_ROOT_DIR}' for all recipe JSONs...")
    resolver.scan_repository()
    print(f"Loaded {len(resolver.recipes)} unique craftable items across the project.")

    # Query item requirements
    target_item = "ae2:pattern_provider"  # Example: "ae2:me_p2p_tunnel"
    quantity = 1

    materials = resolver.get_raw_materials(target_item, target_amount=quantity)

    print(f"\nRaw Base Materials for {quantity}x [{target_item}]:")
    print("=" * 45)
    for material, amount in materials.items():
        print(f" - {material}: {round(amount, 2)}")