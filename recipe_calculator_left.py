import json
import os
from collections import defaultdict
from pathlib import Path


class RecipeCalculator:
    def __init__(self):
        self.recipes = defaultdict(list)  # Maps result_item -> list of recipe definitions
        self.tags = defaultdict(list)     # Maps #tag_name -> list of candidate item_ids

    def load_directory(self, data_path: str):
        """Scans data/ directory for recipe and tag JSON files."""
        data_dir = Path(data_path)
        
        # 1. Load Tags (e.g., data/forge/tags/items/ingots/iron.json)
        for tag_file in data_dir.glob("**/tags/**/*.json"):
            try:
                with open(tag_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Convert file path to tag ID (e.g. #forge:ingots/iron)
                    rel_path = tag_file.relative_to(data_dir)
                    parts = rel_path.parts
                    namespace = parts[0]
                    tag_subpath = "/".join(parts[parts.index("tags") + 2:]).replace(".json", "")
                    tag_id = f"#{namespace}:{tag_subpath}"

                    values = data.get("values", [])
                    for val in values:
                        if isinstance(val, str) and not val.startswith("#"):
                            self.tags[tag_id].append(val)
            except Exception:
                continue

        # 2. Load Recipes (e.g., data/ae2/recipes/*.json)
        for recipe_file in data_dir.glob("**/recipes/**/*.json"):
            try:
                with open(recipe_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._parse_recipe(data)
            except Exception:
                continue

    def _parse_recipe(self, data: dict):
        """Extracts inputs and output from standard & custom recipe JSON formats."""
        if not isinstance(data, dict) or "type" not in data:
            return

        # Extract output item ID and yield count
        result_item, count = self._extract_result(data)
        if not result_item:
            return

        inputs = defaultdict(int)

        # Standard Shaped Crafting
        if data["type"] == "minecraft:crafting_shaped":
            key_map = data.get("key", {})
            pattern = data.get("pattern", [])
            for row in pattern:
                for char in row:
                    if char in key_map and char != " ":
                        item = self._resolve_ingredient(key_map[char])
                        if item:
                            inputs[item] += 1

        # Standard Shapeless & Custom Processing (Inscriber, Smelting, etc.)
        elif "ingredients" in data:
            for ing in data["ingredients"]:
                item = self._resolve_ingredient(ing)
                if item:
                    inputs[item] += 1
        elif "ingredient" in data:
            item = self._resolve_ingredient(data["ingredient"])
            if item:
                inputs[item] += 1

        if inputs:
            self.recipes[result_item].append({
                "yield": count,
                "inputs": dict(inputs)
            })

    def _extract_result(self, data: dict):
        """Finds output item ID and count across vanilla and modded recipe formats."""
        result = data.get("result")
        if isinstance(result, str):
            return result, 1
        if isinstance(result, dict):
            item = result.get("item") or result.get("id")
            count = result.get("count", 1)
            return item, count
        return None, 0

    def _resolve_ingredient(self, ingredient_entry):
        """Resolves tags, dicts, or lists to a single item identifier."""
        if isinstance(ingredient_entry, list):
            ingredient_entry = ingredient_entry[0] if ingredient_entry else {}

        if isinstance(ingredient_entry, dict):
            if "item" in ingredient_entry:
                return ingredient_entry["item"]
            elif "tag" in ingredient_entry:
                tag_id = f"#{ingredient_entry['tag']}"
                if tag_id in self.tags and self.tags[tag_id]:
                    return self.tags[tag_id][0]  # Take first matching item in tag
                return tag_id  # Fallback to tag name if unresolved

        return None

    def calculate_raw_materials(self, item_id: str, quantity: int = 1):
        """Recursively breaks down an item into raw materials."""
        raw_materials = defaultdict(int)
        
        def _break_down(current_item: str, needed: int):
            # Base Case: No known recipe for this item (treated as a raw material)
            if current_item not in self.recipes or not self.recipes[current_item]:
                raw_materials[current_item] += needed
                return

            # Pick the primary crafting recipe
            recipe = self.recipes[current_item][0]
            recipe_yield = recipe["yield"]
            
            # Calculate how many craft operations are required
            crafts_needed = (needed + recipe_yield - 1) // recipe_yield

            for input_item, input_qty in recipe["inputs"].items():
                _break_down(input_item, input_qty * crafts_needed)

        _break_down(item_id, quantity)
        return dict(raw_materials)


if __name__ == "__main__":
    calc = RecipeCalculator()
    
    # Point this path to the repo's 'data' directory or a root containing multiple mod data folders
    # Example: "./Applied-Energistics-2/src/main/resources/data"
    MOD_DATA_PATH = r"Applied-Energistics-2-main\Applied-Energistics-2-main\src\generated\resources\data" 

    if os.path.exists(MOD_DATA_PATH):
        print("Loading recipes and tags...")
        calc.load_directory(MOD_DATA_PATH)
        
        # Target item example: "ae2:density_function" or "ae2:me_p2p_tunnel"
        target_item = "ae2:me_p2p_tunnel"
        amount = 1

        print(f"\nTotal raw materials needed for {amount}x {target_item}:")
        totals = calc.calculate_raw_materials(target_item, amount)
        for item, count in sorted(totals.items()):
            print(f" - {item}: {count}")
    else:
        print(f"Path '{MOD_DATA_PATH}' not found. Please set MOD_DATA_PATH to your mod's data directory.")