import os
import json
import glob
from collections import defaultdict
from typing import Dict, Any, List

class RecipeResolver:
    def __init__(self, recipes_dir: str):
        self.recipes_dir = recipes_dir
        # Maps item_id -> list of recipes that produce it
        self.recipes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        # Set of items user considers "raw" (won't be broken down further)
        self.raw_overrides = set()

    def normalize_id(self, item_id: str) -> str:
        """Standardizes Minecraft IDs (e.g., '#forge:ingots/iron' or 'minecraft:iron_ingot')."""
        item_id = item_id.strip()
        if not item_id.startswith("minecraft:") and ":" not in item_id and not item_id.startswith("#"):
            return f"minecraft:{item_id}"
        return item_id

    def parse_ingredient(self, ingredient: Any) -> str:
        """Extracts a valid item ID from various JSON ingredient formats (tags, lists, objects)."""
        if isinstance(ingredient, list):
            return self.parse_ingredient(ingredient[0])
        elif isinstance(ingredient, dict):
            if "item" in ingredient:
                return self.normalize_id(ingredient["item"])
            elif "tag" in ingredient:
                # Handle tags (e.g., 'c:iron_ingots' or 'forge:dusts/glowstone')
                return f"#{ingredient['tag']}"
            elif "base" in ingredient: # Smithing/AE2 special cases
                return self.parse_ingredient(ingredient["base"])
        return self.normalize_id(str(ingredient))

    def load_recipes(self):
        """Scrapes all recipe JSON files inside the targeted repository directory."""
        json_pattern = os.path.join(self.recipes_dir, "**", "*.json")
        for filepath in glob.glob(json_pattern, recursive=True):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                recipe_type = data.get("type", "")
                
                # Extract Result Item & Count
                result_id = None
                result_count = 1

                if "result" in data:
                    res = data["result"]
                    if isinstance(res, str):
                        result_id = self.normalize_id(res)
                    elif isinstance(res, dict):
                        result_id = self.normalize_id(res.get("item", res.get("id", "")))
                        result_count = res.get("count", 1)

                if not result_id:
                    continue

                # Extract Inputs
                inputs = defaultdict(int)

                # 1. Shaped Crafting
                if "crafting_shaped" in recipe_type or "shaped" in recipe_type:
                    key_map = data.get("key", {})
                    pattern = data.get("pattern", [])
                    for row in pattern:
                        for char in row:
                            if char != " " and char in key_map:
                                ing_id = self.parse_ingredient(key_map[char])
                                inputs[ing_id] += 1

                # 2. Shapeless Crafting / Smelting / Blasting / Special Machines
                elif "ingredients" in data:
                    for ing in data["ingredients"]:
                        ing_id = self.parse_ingredient(ing)
                        inputs[ing_id] += 1
                elif "ingredient" in data:
                    ing_id = self.parse_ingredient(data["ingredient"])
                    inputs[ing_id] += 1
                
                # AE2 Inscriber / Custom Machine recipe fallbacks
                elif "ae2:inscriber" in recipe_type:
                    process_inputs = data.get("ingredients", {})
                    for key in ["top", "middle", "bottom"]:
                        if key in process_inputs:
                            ing_id = self.parse_ingredient(process_inputs[key])
                            inputs[ing_id] += 1

                if inputs and result_id:
                    self.recipes[result_id].append({
                        "count": result_count,
                        "inputs": dict(inputs),
                        "type": recipe_type
                    })

            except (json.JSONDecodeError, KeyError, IndexError):
                continue

    def get_raw_materials(self, item_id: str, target_amount: int = 1, visited=None) -> Dict[str, float]:
        """Recursively resolves an item into its base raw materials."""
        item_id = self.normalize_id(item_id)
        if visited is None:
            visited = set()

        # Custom user overrides or items with no recipes are treated as raw inputs
        if item_id in self.raw_overrides or item_id not in self.recipes or item_id in visited:
            return {item_id: target_amount}

        visited.add(item_id)
        
        # Take the primary recipe for the item
        recipe = self.recipes[item_id][0]
        craft_yield = recipe["count"]
        
        # Calculate how many craft operations are needed
        crafts_needed = target_amount / craft_yield
        
        raw_totals = defaultdict(float)

        for input_id, req_qty in recipe["inputs"].items():
            sub_totals = self.get_raw_materials(input_id, req_qty * crafts_needed, visited.copy())
            for raw_id, raw_qty in sub_totals.items():
                raw_totals[raw_id] += raw_qty

        return dict(raw_totals)


# ==================== EXAMPLE USAGE ====================
if __name__ == "__main__":
    # Point this to your cloned AE2 (or any other mod) repo's data directory.
    # Path inside AE2 repo: Applied-Energistics-2/src/main/resources/data/ae2/recipes/
    MOD_RECIPE_PATH = r"Applied-Energistics-2-main\Applied-Energistics-2-main\src\generated\resources\data" 

    resolver = RecipeResolver(recipes_dir=MOD_RECIPE_PATH)
    
    # Define items you consider "raw base materials" so the script doesn't break them down further
    resolver.raw_overrides = {
        "minecraft:iron_ingot",
        "minecraft:gold_ingot",
        "minecraft:redstone",
        "minecraft:quartz",
        "ae2:certus_quartz_crystal",
        "ae2:sky_stone_block"
    }

    print("Scanning and loading recipes...")
    resolver.load_recipes()

    # Target Item & Quantity to calculate
    target_item = "ae2:me_p2p_tunnel"
    amount = 1

    materials = resolver.get_raw_materials(target_item, target_amount=amount)

    print(f"\nRaw Materials needed for {amount}x [{target_item}]:")
    print("-" * 40)
    for mat, qty in materials.items():
        print(f" - {mat}: {round(qty, 2)}")