#!/usr/bin/env python3
import os
import shutil

def sync_cursor_commands():
    repo_file = "cursor-commands.json"
    user_folder = os.path.expanduser("~/.cursor")
    target_file = os.path.join(user_folder, "cursor-commands.json")

    if not os.path.exists(user_folder):
        os.makedirs(user_folder)

    shutil.copyfile(repo_file, target_file)
    print("✅ Custom commands synced to Cursor config folder. Restart Cursor to see them.")

if __name__ == "__main__":
    sync_cursor_commands()
