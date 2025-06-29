DayZ Texture Exporter - Instructions
====================================

This tool helps DayZ modders convert standard PBR textures (BaseColor, Normal, AO, Metallic, Roughness)
into the texture maps that DayZ uses: _co, _nohq, _as, and _smdi. It also converts them to .paa
using DayZ Tools.

----------------------------------------------------
How to use this script:
----------------------------------------------------

1. Install Python (3.10+ recommended).
   👉 https://www.python.org/downloads/

2. Install the required Python libraries:
   Open your terminal or command prompt and run: pip install Pillow PyQt5

3. Make sure you have DayZ Tools installed from Steam.
- You'll need ImageToPAA.exe.
- These are in your DayZ Tools folder:
  ```
  C:\\Program Files (x86)\\Steam\\steamapps\\common\\DayZ Tools\\Bin\\ImageToPAA\\ImageToPAA.exe
  ```

4. Place `TexConvert.py` and your `dayz_texture_exporter_icon.ico` (optional) in the same folder.

5. Run the script:
- Open a terminal in this folder.
- Run:
  ```
  python TexConvert.py
  ```

6. The exporter GUI will open:
✅ Drag and drop your PBR maps into each slot OR click Browse.  
✅ Pick your output folder.  
✅ Pick your resolution (512, 1024, 2048, 4096).  
✅ Choose which DayZ maps to export.  
✅ Set your output base file name.  
✅ Select your converter `.exe`.  
✅ Click Convert and wait!

7. The tool will:
- Combine channels as needed (_as and _smdi)
- Resize the textures
- Save them as .png
- Call ImageToPAA/PAAConverter to make .paa files
- Show progress and logs as it runs

8. Find your new .paa textures in the output folder you picked.

----------------------------------------------------
⚠️ DISCLAIMER:
----------------------------------------------------
This is a **work in progress** tool! It might not work perfectly every time.
Always keep backups of your original files and test your exports in-game.

----------------------------------------------------
Having problems?
----------------------------------------------------
✅ Double-check your paths.  
✅ Make sure you selected the correct DayZ Tools converter.  
✅ Run the script as admin if you hit permission errors.  
✅ Feel free to submit issues or ideas on GitHub!

Happy modding! 🧃
