import asyncio
import os
from gdrive_service import extract_gdrive_id
import database
import config

async def test_gdrive_extraction():
    # Standard URL
    url1 = "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/view?usp=sharing"
    assert extract_gdrive_id(url1) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

    # Export URL
    url2 = "https://drive.google.com/uc?id=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms&export=download"
    assert extract_gdrive_id(url2) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

    # Raw ID
    raw = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    assert extract_gdrive_id(raw) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    print("[OK] GDrive URL extraction passed")

async def test_database_folders_and_shares():
    await database.init_db()
    
    # Create folder
    f1 = await database.create_folder("Portfolio_Site", None)
    assert f1["name"] == "Portfolio_Site"
    f1_id = f1["id"]
    
    # Create subfolder
    f2 = await database.create_folder("assets", f1_id)
    assert f2["name"] == "assets"
    assert f2["parent_id"] == f1_id
    f2_id = f2["id"]
    
    # Add index.html to f1
    index_file = await database.add_file("index.html", 500, "text/html", f1_id, 2001, "me")
    assert index_file["name"] == "index.html"
    
    # Add css to f2 (subfolder)
    css_file = await database.add_file("style.css", 250, "text/css", f2_id, 2002, "me")
    assert css_file["name"] == "style.css"
    
    # Check website detection
    has_web = await database.check_folder_has_website(f1_id)
    assert has_web is True
    
    # Check relative path resolution for website hosting
    resolved_root = await database.get_file_by_relative_path(f1_id, "index.html")
    assert resolved_root is not None
    assert resolved_root["id"] == index_file["id"]
    
    resolved_asset = await database.get_file_by_relative_path(f1_id, "assets/style.css")
    assert resolved_asset is not None
    assert resolved_asset["id"] == css_file["id"]
    print("[OK] Static Website Path Resolution passed")
    
    # Check recursive tree for ZIP download
    all_tree = await database.get_folder_files_recursive(f1_id)
    assert len(all_tree) == 2
    rel_paths = [x["relative_path"] for x in all_tree]
    assert "index.html" in rel_paths
    assert "assets/style.css" in rel_paths
    print("[OK] Recursive Folder Files Tree passed")
    
    # Move folder test
    target_parent = await database.create_folder("All_Websites", None)
    moved = await database.move_folder(f1_id, target_parent["id"])
    assert moved is True
    
    f1_updated = await database.get_folder(f1_id)
    assert f1_updated["parent_id"] == target_parent["id"]
    print("[OK] Move Folder passed")
    
    # Clean up
    await database.delete_folder_recursive(target_parent["id"])
    print("[OK] Clean up passed")

if __name__ == "__main__":
    asyncio.run(test_gdrive_extraction())
    asyncio.run(test_database_folders_and_shares())
    print("[SUCCESS] All backend tests passed successfully!")
