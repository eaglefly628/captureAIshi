Universal Unreal Engine 4 Unlocker (UUU) v4
==========================================================
(for reasonably recent engines, 2016+)

UUU Version: v4.11.2
----------------------------------------------------------------

   For updates and support: https://www.patreon.com/Otis_Inf
   For documentation, please visit: https://opm.fransbouma.com/uuuv4.htm

----------------------------------------------------------------

Changelog
==============
v4.11.2:
    - Added: Overlay, Pose editor: an extra tab was added to the bone tree panel which shows all the bones that were recently changed. This will make it 
             easier to work on a set of bones without having to scroll the tree to find them back 
    - Added: Overlay, Pose editor: an ability was added to show where a bone is when it's hovered in the bone tree: a blue semi-transparent circle will 
             be displayed at the location of the currently hovered bone in the bone tree in the pose editor. This will make it easier to find the right 
             bone to adjust the actor's pose 
    - Fixed: When switching between actors A and B where actor A has more sub components than actor B, it could be that the pose editor wouldn't show for 
             B when selecting that actor. 
    - Changed: Overlay, Pose editor: the pose editor now remembers the last selected bone when switching between actors. 
    - Changed: Overlay, Pose editor: the bone tree now remembers which component nodes in the bone tree were expanded and which ones were collapsed when 
               switching between actors 
    - Added: Overlay: Added an option to the Actor manipulation tab in the overlay to keep changes made after the camera has been disabled. 
    - Added: Added additional validation for an unreal object being still active when it's e.g. reset by the UUU 

v4.11.1:
    - Fixed: (IGCS, Client, Hotsampling tab) It could be the Hotsampling tab didn't have the default aspect ratios displayed so only the native monitor 
             aspect ratio was added by default. 
    - Fixed: an attached light wasn't showing up as such on the client light list 

v4.11.0:
    - Fixed: (IGCS, Client, Hotsampling tab) The controls were configured wrong so the Refresh button wasn't properly aligned, causing wasted space next 
             to the splitter bar 
    - Fixed: Reading an enum property of a class no longer crashes the UUU on old engines 
    - Added: The overlay now has a Light tab, which allows users to create and manipulate lights from the overlay. It also offers light rotation and location 
             manipulation through a gizmo, and offers light visualizers which are better than the engine arrow variant from older versions which weren't 
             always showing up. 
    - Added: Exposed additional light properties to the light editor in the overlay (not the client) 
    - Fixed: Copying a light didn't copy all properties of a light correctly 
    - Fixed: All properties of a light are now updated immediately from the client, instead of lagging behind. This greatly speeds up e.g. shadow related 
             properties like Contact Shadow Length and Shadow Bias among others. 
    - Fixed: When changing a gizmo setting in the overlay and not in the menu, it could be the setting wasn't saved to the ini file 

v4.10.3:
    - Fixed: Updated for Days Gone Remastered (partly) 
    - Fixed: The change added for 4.10.2 to instantiate the game specific cheat manager could backfire and cause crashes when a new level was loaded due 
             to the game not anticipating the cheat manager is live. They crash beause no code is in place to clean up the world reference. This change 
             has been reverted to the code that was in the UUU before so the cheat manager isn't really active. It'll be re-added later with an optional 
             button. This happens e.g. in Stellar Blade and potentially other games. 

v4.10.2:
    - Changed: (IGCS, Hotsampling) Added a way to specify new aspect ratios and delete aspect ratios for the hotsampling resolution tree. The resulting 
               list of aspect ratios is persisted per client. 
    - Changed: If no cheat manager is set, the uuu can now recreate a new one and will use the game-specific variant, which should offer the functions 
               defined in these specific cheat managers to the console. This works e.g. with Stellar Blade and will reinstate the game specific cheat manager 
    - Fixed: Pose tooling: If a root bone was changed in a component, it was always synced with all root bones of all other skeletal mesh components of 
             the actor, regarding of whether that root bone represented the same root. This could cause hair and other components become disaligned when 
             loading a pose or changing a root bone's angles or location. 
    - Fixed: Pose tooling: clicking reset on the "Reset rotation" button for a bone didn't properly reset the angles in all cases 

v4.10.1:
    - Fixed: Added compatibility changes for Stellar Blade 

v4.10.0:
    - Fixed: If the fov was set to a very low value, the movement reduction factor wasn't properly calculated and it resulted to a faster movement again. 
    - Added: Selecting an actor or bone will optionally display an editor gizmo to rotate and move the actor or bone in the 3D world as an alternative 
             to the sliders in the overlay GUI. Gizmo's will work with games using UE 4.24 and up, as it requires a function to be present. 
    - Fixed: Rotation sliders for actors now properly flip over after going to the edge of -180 or 180 degrees so it's no longer needed to move the slider 
             to the other side to keep on rotating 
    - Fixed: Skeletal Mesh Actors weren't always marked as movable when selected 

v4.9.15:
    - Fixed: The UUU couldn't find essential objects in South of Midnight gamepass version, nor did the FoV work 
    - Fixed: Generalized some patterns for 4.27+ games 

v4.9.14:
    - Fixed: 4.9.13 contained a bug where if the engine version wasn't found, the type cache could harm version detection so it would detect the wrong 
             engine version and the game could crash 

v4.9.13:
    - Fixed: IGCS: code refactoring of the quaternion to angle system accidentally removed the code to mark the camera as changed when the user tilted 
             the camera 90 degrees or reset the tilt/roll using the keyboard. 
    - Changed: A better player coordinate smoother which keeps a rolling average over the last 60 coordinates of the player and this seems to eliminate 
               any player stutter when a camera path is playing relative to the player 
    - Changed: Implemented a better type cache to avoid rare crashes 
    - Fixed: Resetting the skeletal mesh on an actor could set the original animation mode to an undefined state 
    - Changed: IGCS: Moved the Display Notifications checkbox to the configuration tab, and all new tool builds will have that from now on. 
    - Fixed: Better compatibility with some v4.27 engines (e.g. South of Midnight) 

v4.9.12:
    - Fixed: In 4.9.11 a bug was introduced where rotating a bone in the bone editor would use an incomplete set of angles, causing the bone to snap to 
             a different position. 

v4.9.11:
    - Fixed: IGCS: Added more reliable code to prevent crashes when rendering the overlay while hotsampling 

v4.9.10:
    - Fixed: In some games the keybinding for opening the overlay wasn't taking effect as the client sent the setting value before the keybinding was registered. 
    - Fixed: A potential crash could occur when the pose editor was open and the user clicked an actor without a bone tree (e.g. a static mesh actor) 
    - Added: Ability to import a part of the bone tree from a saved pose file. This way you can e.g. import the face bones from a .uuupose file in the 
             current pose you have on an actor. 

v4.9.9:
    - Fixed: Using a recent version of the FF7Rebirth fix mod to properly get ultrawide support for the HUD together with the UUU could cause oversized 
             GUI elements because the UUU didn't detect the mod being present and assumed it had to auto-correct the HUD for ultrawide. I've removed this 
             code now, so for UW support for the HUD in FF7Rebirth, please use Lyall's mod. See UUU gameslist for the link. 

v4.9.8:
    - Fixed: Final Fantasy VII Rebirth: Added workarounds for when the UUU was used intogether with the Ultrawide mod by Lyall 
    - Fixed: Final Fantasy VII Rebirth, EGS version: The namesstore wasn't found as the game executable is apparently compiled with lower optimization 
             settings. 
    - Fixed: If the CVars in the ConsoleManager contained a non-ascii character in the helptext, the cvars output stopped at that cvar, even though the 
             code has support for unicode characters. 
    - Fixed: Final Fantasy VII Rebirth: on e.g. the EGS version, a UUU tweak to be able to move the camera during an in-game photomode was actually blocking 
             essential copying, causing the camera not to move/rotate. 
    - Added: Final Fantasy VII Rebirth: The UUU will now kill the Vignette automatically. They're using different postprocess settings so the ones configurable 
             in the UUU aren't used in the game, they're using their own. 

v4.9.7:
    - Fixed: Engines with case sensitive name stores (basically compiled with Editor data) would crash when the UUU tried to obtain a name 
    - Added: Support for Final Fantasy VII Rebirth. Please see the UUU v4 doc page's gamelist for details about supported features 

v4.9.6:
    - Fixed: Added pose tool support for The First Bezerker: Khazan and potentially other 4.27 games which weren't compatible with the pose tools 
    - Changed: The default for Screen Space Reflections Max Roughness is now 1.0, the max value. Before, it was 0.0, the minimum value, however normally 
               you'd crank this up as high as possible. 
    - Changed: All lights will now have their IntensityUnits set to Lumens and the maximum intensity values have been retweaked to be in line with that 
               change. This gives brighter lights in daylight lit areas in some games so they're actually visible, like in Hogwarts Legacy. Before, the 
               UUU would keep the game's default (often 'UnitLess'), which was usually enough, but sometimes (like in Hogwarts Legacy) it made lights not 
               bright enough outdoors. 
    - Fixed: The Light intensity max value/slider combination wasn't really setup to receive high values. It's now possible to specify a very high intensity 
             max value, e.g. 20,000,000,000, which allows daylight outdoor lights to be used. An example is Hogwarts Legacy where outdoor lights weren't 
             showing up in most cases as the intensity was too low 

v4.9.5:
    - Fixed: Added another AOB pattern for GEngine location detection 

v4.9.4:
    - Fixed: The crash guard check added to 4.9.3 was causing issues in some games, so a new better fix was added which solves this and also makes sure 
             the UUU won't crash during engine version detection 
    - Fixed: Added proper engine version detection for Hogwarts Legacy 

v4.9.3:
    - Fixed: Added a safeguard check to the detector for engine version, so e.g. Dragon Quest XI now works without crashing after injection 
    - Fixed: Fixed pose editor for some 4.18 games. 

v4.9.2:
    - Fixed: Added support for low level RawInput buffer blocking/reading so some games which exclusively use GetRawInputBuffer (hello Star Wars Jedi Survivor) 
             now support the mouse as camera device and support the mouse in the overlay without crappy alt-tab work arounds. 

v4.9.1:
    - Fixed: When you enabled pose editing on an actor and then either clicked 'Reset actor state' or disabled the camera, the morph targets weren't reset 
             properly 
    - Fixed: In some games cloning an actor could take more time than it would take the UUU to cache the clone's mesh and components, leading to the clone 
             being seen as not a full skeletal mesh component and thus that the pose tool wasn't available. 

v4.9.0:
    - Fixed: Cloning a character will now set the clone's skin/skeletal mesh properly 
    - Fixed: Cloning a character in a game with engine version 4.19 or older could lead to the list of animations to select on clones to be wrong 
    - Added: Morph target support in the pose editor for games that support morph targets. Morph targets are specific changes to parts of the skeletal 
             mesh. Changes made to these are saved with a pose. 
    - Fixed: Clicking on an actor in the world no longer will select actors that are 'hidden'. 
    - Added: Sub-component support per actor for posing, including playing animations on a sub component (e.g. the face). 
    - Changed: More animations are visible in the drop down list for custom animations to play on a mesh and they're now sorted by name 
    - Fixed: Saving a pose now properly generates a filename for the first time and navigating a to a different folder no longer clears that initial filename 
    - Added: If a game locked the fov in the PlayerCameraManager, it's now set by the UUU camera when it's enabled, making it possible to change the FoV 
             when the camera is enabled 

v4.8.2:
    - Fixed: When playing back a camera path, a roll/tilt angle wasn't properly set 

v4.8.1:
    - Fixed: In a rare occasion it was possible to have the pose editor open when the camera was disabled, which suggested the user could change the pose 
             which wasn't the case 
    - Changed: Bumped up the min/max delta for actor movement from 100m to 500m 
    - Changed: Changed the default overlay opacity to 0.99 as the overlay could otherwise have color issues in Hogwarts Legacy on some systems 
    - Fixed: Unpausing NPCs could potentially crash the game if the engine had garbage collected one or more NPCs that were paused 

v4.8.0:
    - Added: Pose editor in games that are supported for this feature; you can manipulate any bone in an actor (e.g. your character, an enemy) to pose 
             them how you like it. 
    - Fixed: Much better selection code for selecting actors in a scene. 

v4.7.3:
    - Fixed: Small fix to remove a mouse pointer issue when the overlay is visible: the mouse wasn't movable outside a small area in the game window 

v4.7.2:
    - Fixed: the selected actor was always scrolled into view and therefore it made scrolling the whole window impossible at times 
    - Fixed: in some games, the FoV didn't work, because the PlayerCameraManager's fov value wasn't set to 0 

v4.7.1:
    - Fixed: Deleting a light could crash the game in the previous release. 
    - Added: Added a setting on the IGCSClient Configuration tab for controlling the aspect ratio axis constraint, which is which field of view angle (vertical 
             or horizontal) is kept when the aspect ratio changes (which e.g. happens when the letter/pillarboxes are removed or when you change the aspect 
             ratio of your window). In earlier versions, the UUU decided by itself what was best, but this could lead to zoomed in images when the aspect 
             ratio constraint was removed. 
    - Added: Added a key binding editor for toggling the in-game overlay 

v4.7.0:
    - Fixed: New pattern added for SWidget blendopacity to hide the hud in some games. 
    - Added: In-game overlay for actor selection and manipulation, which allows you to clone/rotate/move any asset in a game world, as well as change the 
             mesh and animation on some skeletal mesh actors (e.g. enemies). Open the in-game overlay with Ctrl+<key to enable the camera>, so by default 
             Ctrl-Insert. It's mandatory to read the updated documentation for this feature! 

v4.6.13:
    - Fixed: If the dll was loaded from a path which contained non-ascii characters, the injection would fail with a cryptic error. It will now properly 
             load the dll from a path with non-ascii characters. 
    - Added: Another pattern for GObjects array as it sometimes failed to match for 4.27, causing crashes as the wrong code was matched with the wrong 
             pattern. 

v4.6.12:
    - Added: 3D visualizers in-game for Lights, if the game uses UE4.25+. You can toggle them on/off (default off) using a button on the lights tab and 
             using a keyboard shortcut (default ';', but bind a different key you like to use instead if ';' isn't suitable for you). Spotlights now have 
             an arrow starting at the spotlight location pointing in the direction the spotlight is shining at, pointlights get a 6 arrow object at the 
             location of the light. The visualizers are drawn in the color of the light. 
    - Fixed: A pattern for UWorld::Pause had the wrong offset defined for the pause instruction, which rendered it useless. E.g. it now works in Gotham 
             Knights. 

v4.6.11:
    - Added: Support for black bar removal in The Invincible. This has been implemented as a special case and is only activated when you enable the camera, 
             because the game's on-screen icons are otherwise off and it's much harder to trigger actions. 

v4.6.10:
    - Fixed: Rearranged GObjects array patterns so less false positives would occur due to a pattern added for old(er) games build with CLang (FF7R, tales 
             of arise etc.) so games which wouldn't work before could now work. 
    - Fixed: Added an alternative AOB for e.g. Mortal Kombat 1 and potentially other games build with 4.27 which had a false positive for the GObjects 
             array and therefore didn't work well... 
    - Added: Added a previous/next light button pair at the top of the Light editor window to cycle through the lights without the necessity to go back 
             to the main light list. 

v4.6.9:
    - Fixed: On modular builds (e.g. Returnal), and some other games where the ConsoleManager wasn't found, the UUU would crash as it didn't properly handle 
             the situation when the console manager wasn't found. 

v4.6.8:
    - Added: Readonly CVars and commands are now unlocked without dumping them to a file. 
    - Added: Cvars are now also dumped in a .json file, additionally to the .txt file the UUU already wrote to. 
    - Fixed: Issue where CVars dumping on older engines didn't insert carriage returns at the end of the lines. 
    - Changed: CVars help text and flag values are now dumped starting with UE4.19, so older engines are better supported. 

v4.6.7:
    - Added: On the Available Features tab, you can now click 'Dump CVars' (when supported by the game) and it'll dump a file with all the cvars/commands 
             you can use on the console, with the help text (UE4.20+) and the type + current value of the variable (UE4.24+). This file is placed next 
             to the objects dump file you can create on the same tab, using the filename "UUU_CVarsDump.txt" 
    - Fixed: Camera movement shake strength was affected by how high the movement speed was set. This isn't the case anymore. 

v4.6.6:
    - Added: The mousewheel can now be used on the sliders to move the value. 
    - Added: Shift / Shift+Ctrl are now usable on the sliders to have them move slower and even more slower 
    - Fixed: Additional patterns added for constructs needed to reinstate the console for some games. 
    - Added: Keybinding for deleting the active node on the current path 
    - Added: Keybinding for deleting the current path 
    - Added: Keybinding for appending a new node after the active node on the current path 
    - Added: Ability to configure which gamepad stick is used for rotating/moving the camera (for left-handed users). 
    - Added: Ability to configure which gamepad trigger is used for moving camera up/down 

v4.6.5:
    - General: Added a new way to remove letter/pillar boxing which e.g. in Survivor now correctly removes black bars in cutscenes without introducing 
               FoV artifacts. 
    - Fixed: Star Wars Jedi: Survivor specific: The FoV value wasn't properly reported to the IGCSConnector reshade addon. 

v4.6.4:
    - Added: Added support for Star Wars Jedi: Survivor 

v4.6.3:
    - Fixed: Camera path playback ease in / out are now no longer causing a hike in speed to compensate for the slow down/speed up but use proper animation 
             curves mapped across the entire path. 
    - Fixed: Playing a camera path and moving / rotating the camera using mouse/controller could slightly influence the camera during playback. 
    - Fixed: When storing the camera state using ctrl-f1/f2/f3 and then restoring it using f1/f2/f3 would flip the roll angle from negative to positive 
    - Added: All camera code now runs on the game thread of the game. This makes 100% synchronized camera movement together with character movement possible 
             without the stuttering of the character that was present in previous versions. A previous attempt was unsuccessful, but this time it's more 
             reliable and it's expected to work with all supported games. It implements a fallback to the older system in the rare case it doesn't work 
             as intended. 
    - Added: Scanning of patterns is now done in parallel which greatly speeds up initialization time on large executables. 
    - Added: Support for IGCS Connector v2.0 so you can record reshade states with camera path nodes. 

v4.6.2:
    - Added: Yet another way to hide HUD elements which might help hiding the HUD in some games. 
    - Added: Sword & Fairy 7 v2 builds were broken as they have a customized namepool now. Support for this has been added. 

v4.6.1:
    - Changed: The strength of the rotation shake on roll has been reduced, it's now half as strong. 
    - Fixed: When selecting Keyboard/Mouse as camera device and having camera shake active, the movement smoothing options didn't work properly. 

v4.6.0:
    - Fixed: When you have Npc animation speed override enabled and you pause the Npcs using the Npc pause key, and you unpause the Npcs again with the 
             Npc pause key, the Npcs will now correctly resume with the Npc animation speed you've set in the UUU client. Previously the Npcs stayed paused. 
    - Fixed: Npc pause now no longer sets PlayersOnly on the cheat manager so it won't pause the player pawn anymore in some games 
    - Fixed: The UUU (and other future cameras) will now hook all xinput libraries so there's no more issue with when to inject the UUU to make it able 
             to block gamepad input. (If the game reads gamepad input through XInput of course) 
    - Added: Time of Day control for Hogwarts Legacy. 
    - Added: Depth of field focal distance, Depth of Field f-stop, Auto exposure bias and Vignette values are now recorded in camera path nodes so you 
             can change these within a path to e.g. keep elements in focus with the in-engine DoF and correct auto exposure. 
    - Added: Toggle all on/off buttons in post processing. 
    - Added: Double-clicking a post processing slider's button will reset it to the default value 
    - Added: Camera shake controls in both manual movement (for hand-shot videos) and camera paths. 


How to use
===========
Please do the following: Run the game and then the IGCSClient.exe. If the game runs as administrator, you have to run the 
IGCSClient.exe also as administrator, but this isn't required. In the IGCSClient, click 'Select' to select the game process to inject the dll into. 
This is usually a gamename-win64-shipping.exe process. When you've selected the game to inject the dll into, click the 'Inject dll' button. 

Don't close the client, it's your tool to the camera for configuration
There's a Help tab in the GUI. Please read it. 

Camera control device
========================
In the configuration tab of the IGCS Client, you can specify what to use for controlling the camera: 
controller, keyboard+mouse, or both. The device you pick is blocked from giving input to the game, 
if you press 'Numpad .' (On by default). 

About custom lights
====================
If the game supports custom lights, you can create new lights on the lights tab (or use one of the keyboard shortcuts). 
By clicking the pencil button you can open the editor of a created light. When the editor is open, clicking the pencil button 
of another light will open that ligth in the editor instead. Changes you make are taking effect immediately. 

The light editor has several numeric textboxes like the x/y/z position. To change the values in these, click inside the box and
use your mousewheel to change value. Use shift + mousewheel to take bigger steps and ctrl + mousewheel to take small steps. 

Sometimes the engine will glitch and stop updating a light, e.g. when it's attached to the camera. To recover from this, switch the light
off and on again (yes, really) and it'll continue working. I don't know what the reason is for this. 

NOTE: when you're done with the lights for a scene, delete them. Especially newer engines can hang when loading a new level when there are 
existing lights. The tools have a checker which runs every 10 seconds but this isn't 100% fail safe. 

NOTE: not all features work in older engines. If you think it should work but it doesn't, please let me know and I'll have a look. Lights in UE4
went through a lot of changes starting in UE v4.18+, so if you're playing a game that's older than that, expect a lot of the features to have little or no effect. 

About hotsampling support
==========================
To take screenshots at higher resolutions than your regular gaming resolution, run the game in windowed mode. 
To get rid of the window border, on the Hotsampling tab, click 'Fake fullscreen'. 
To switch to a high resolution, select the resolution and aspect ratio you want from the tree on the Hotsampling tab and click 'Set'. 
You can also select one from the list of previous used resolutions if you switch between a given set of resolutions frequently. 
If the resolution fits your monitor, the game will add a border, you have to click 'Set' again to get rid of it. 

The IGCS client will resize the game window to the requested resolution and the game will resize the game 
framebuffer accordingly, allowing you to take a shot at a high resolution. To go back to your regular gaming 
resolution, simply click the 'Fake fullscreen' button again.

About the multiple timestop systems.
=====================================
The UUU has two ways to pause the game: using the normal UWorld::IsPaused hack, (Numpad 0), and one using the slomo command code, (Page down).
You can use either one, if they're both found of course. Numpad 0 is a hard-pause which could lead to TAA jitter in the scene. You can 
remove that by stepping down the AA a bit, using: r.postprocessaaquality 2 in the console. To set it back, use r.postprocessaaquality 6.
The downside of that is that cutscenes might play on and the lower quality AA might remove some effects. 

The slomo based pause using Page Down doesn't suffer from TAA jitter, and can pause most, if not all, cutscenes as well (except audio in some
situations). In general, if the latter is supported, you should use the slomo based pause. 

About invulnerability
======================
The UUU has a simple invulernability setting that switches bCanBeDamaged off on your player character. This might not work in most games, 
so try before relying on this in combat scenes. 

About character scaling
========================
The UUU can scale your character in-game's size. Use the Player size slider for that. If you have paused the game, changing this slider doesn't
have an immediate effect; the engine requires user input to make the character change its size. To do that in a paused game: press a directional key 
to move the character or use your controller, and then press the Skip frame button (By default End) to skip a frame. 
You can also use this to hide your character: set the size to 0 and your character is invisible. 

Built-in camera system
=========================
The UUU comes with a built-in sophisticated camera system you can configure yourself using the keybinds in the Configuration tab. You can
select which device you'll use for camera movement (By default both kb/mouse and controller are selected). 

Troubleshooting
===================
If you enable the debug camera with toggledebugcamera, you might see info on the screen. Remove that by pressing backspace (or controller X).

You might get an error with older games that it can't find the EngineVersion key and it will fall back to the default version.
It will then try to auto-detect which engine version is being used. If that fails, it's likely not going to work. If it succeeds, 
the console can be created most likely. 

If you get AOB errors when injecting the dll, it might be the engine's code hasn't been fully initialized yet and AOB scanning can't
find it. Simply load a level and try again by pressing CTRL+END. 

The built-in HUD toggle might not work if the HUD is built with a custom HUD system like scaleform. In that case the hud toggle won't hide
the HUD. If that's the case, you might want to try 'showhud 0' (without the quotes) to hide the hud and 'showhud 1' to show it again in the console.
This might not always work, it depends per game. 

It might be you see an error about AllowCheats not being found. This might not be a problem: some games don't disable this or have the code
which selects whether cheats are allowed at all stripped out and allow cheats regardless. All you have to do is type `Enablecheats 1` (without
the quotes) in the console to enable the debug camera.

In-game console doesn't open
---------------------------------
If the console doesn't open when pressing ~, but all AOBs are found, please do the following:
In the IGCSClient, go to the Configuration tab. In there you can select the key to open the in-game console.
By default the key is '~' or 'Tilde'. Please select a key you don't use in-game and which is available on your
keyboard without using Shift. E.g. if you have a French keyboard (Azerty), you can choose 'Dollar ($)', which means you can 
press the $ key to open the console, which is right above the Enter key on most Azerty keyboards. 

Alternatively, you can choose a US-en keyboard layout, or add a custom key to the ini file of your game, but this might not
always work:

Go to:
c:\users\<your username>\AppData\Local\gamename\Saved\Config\WindowsNoEditor

open Input.ini
Add (pay attention to the empty line!):

[/Script/Engine.InputSettings]
ConsoleKey=Tilde

Save and set to readonly. You can also set it to another key, e.g. K. 

Have fun and create beautiful shots, m'kay? 

Cheers!

Otis_Inf