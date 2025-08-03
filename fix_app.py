#!/usr/bin/env python3
"""
Quick script to fix the duplicate code in app.py
"""

def fix_app_file():
    # Read the file
    with open('app.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the problematic section and clean it up
    # Look for the line "logger.info(f"Sample of Gemini response: {ai_response[:sample_length]}...")"
    # and then find the next line that says "# Define helper function for finding potential misspellings"
    
    start_idx = None
    end_idx = None
    
    for i, line in enumerate(lines):
        if 'Sample of Gemini response:' in line and 'logger.info' in line:
            start_idx = i + 1  # Start right after this line
        elif '# Define helper function for finding potential misspellings' in line:
            end_idx = i
            break
    
    if start_idx is not None and end_idx is not None:
        print(f"Found problematic section from line {start_idx+1} to {end_idx+1}")
        print(f"Removing {end_idx - start_idx} lines of duplicate code")
        
        # Create the fixed content
        fixed_lines = lines[:start_idx]
        
        # Add the proper except block
        fixed_lines.extend([
            "        \n",
            "        except Exception as e:\n",
            "            logger.error(f\"Error in AI analysis: {str(e)}\")\n",
            "            # Create a default response with the error\n",
            "            ai_response = json.dumps({\n",
            "                \"issues\": [{\n",
            "                    \"title\": \"AI Analysis Error\",\n",
            "                    \"severity\": \"High\",\n",
            "                    \"description\": f\"Error during analysis: {str(e)}\"\n",
            "                }],\n",
            "                \"recommendations\": [\"Please try again with a different image or check system logs.\"]\n",
            "            })\n",
            "        \n",
        ])
        
        # Add the rest of the file starting from the helper function
        fixed_lines.extend(lines[end_idx:])
        
        # Write the fixed file
        with open('app.py', 'w', encoding='utf-8') as f:
            f.writelines(fixed_lines)
        
        print("Fixed app.py - removed duplicate code and fixed except block")
        return True
    else:
        print("Could not find the problematic section")
        return False

if __name__ == '__main__':
    fix_app_file()