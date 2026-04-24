Universal Unreal Engine 5 Unlocker (UUU) v5
==========================================================

UUU Version: 5.8.7

----------------------------------------------------------------

   For updates and support: https://www.patreon.com/Otis_Inf
   For documentation, please visit: https://opm.fransbouma.com/uuuv5.htm

----------------------------------------------------------------

IMPORTANT: For games using Unreal Engine 5.1 or higher. 

Changelog
==============
v5.8.7:
    - Fixed: Atmospherics weren't usable in Code Vein 2 because its time of day control interfered 
    - Fixed: In the atmospherics tab in the overlay, two reset buttons had the wrong ID and therefore reset two sections at once 
    - Fixed: Enabling an atmospheric element for editing could crash the game in certain games. 
    - Fixed: UE 5.7 introduced a different layout of the objects in the objectsstore, which caused crashes when the UUU was injected in a game using UE5.7. 
    - Fixed: Updated with the updated engine code for Black Myth: Wukong so custom workarounds now work again 

v5.8.6:
    - Changed: (IGCS, Overlay). Migrated to ImGui 1.92.5 and implemented truetype font support as well as font selection from a select set of fonts (MS 
               Sans Serif, Arial, Consolas, Segoe UI, Calibri, Tahoma, Verdana and the imgui font Proggy). Also made the overlay dpi aware so it should 
               scale automatically already on high dpi displays 
    - Fixed: (IGCS, Overlay, Settings) in some situations it could be the settings for the overlay were read after they were applied and therefore didn't 
             take effect. 
    - Fixed: The Outer Worlds 2's latest patch caused some patterns to match with the wrong pieces of code. 
    - Fixed: Updated for 5.6.x debug builds (e.g. Star Rupture). Can still crash due to debug code in classes and helper functions causing issues when 
             e.g. creating lights or clicking on actors 
    - Fixed: Added more patterns to make Grounded 2 'work'. Had to add a workaround as Obsidian renamed an essential Unreal Engine class which caused problems. 
    - Fixed: Added fixes for Code Vein II, and other UE 5.4+ engines. 

v5.8.5:
    - Fixed: Because it's almost xmas: Updated for S.T.A.L.K.E.R. 2 

v5.8.4:
    - Fixed: Added more patterns for 5.5+ 
    - Fixed: Corrected a structural problem with metahuman expressions: if the game had multiple skeletons using metahuman bones, it could be the game 
             would crash or apply the expression on the wrong bones. This adds support for metahuman expressions for more games, e.g. Lost Records: Bloom 
             & Rage 
    - Fixed: Updated for Borderlands 4's patch released on 12-12 

v5.8.3:
    - Fixed: Added more patterns for UE 5.5+. 
    - Fixed: Added yet more patterns for Stalker 2. 

v5.8.2:
    - Fixed: Hotfix for 5.8.1, as the changes added for stalker 2 weren't sufficient 

v5.8.1:
    - Fixed: Light color on the client had Red swapped with Blue compared to the light in-game. 
    - Fixed: Added compatibility again for Stalker2. 

v5.8.0:
    - Fixed: Added more Objectstore patterns, more spawn actor patterns and more pose function patterns 
    - Fixed: 5.7.7 introduced a regression where the newly added patterns for The Outer Worlds 2 caused crashes in Avowed as they matched there too. This 
             has been corrected 
    - Added: Added atmospherics tweaking for Directional Lights (sun/moon), Exponential height fog, Sky Atmosphere and Volumetric Cloud to the UUU overlay. 
    - Fixed: If a component had just a few metahuman bones, it was considered a metahuman component, but this could cause mismatches with the actual metahuman 
             skeleton, resulting in crashes. MetaHuman expressions should now work fine on games like Oblivion Remastered 

v5.7.7:
    - Fixed: Updated for The Outer Worlds 2 

v5.7.6:
    - Fixed: Added more patterns for the HUD toggle 
    - Fixed: Added a more generic way to lift the aspect ratio constraint in the PlayerCameraManager 
    - Added: Added MetaHuman face expressions to the pose editor in the overlay, so it's now very easy to apply an expression to a character's face if 
             the game uses MetaHuman. You can blend multiple expressions to your liking to create a unique look. 

v5.7.5:
    - Added: The Load Pose dialog now has a case-insensitive file filter so you can limit the amount of files you see in the folder browser, in case you 
             have many pose files 
    - Changed: Bone name / morph target name filtering is now case insensitive 
    - Fixed: Rotating an actor / object using the gizmos or delta sliders and then clicking reset causes the object to be wrongly oriented. 
    - Fixed: Made sure the Show Pose Editor button isn't shown when there are no bones found in the skeletal mesh due to a structural change in the component 
             type, as the editor won't be displayed when that's the case 
    - Fixed: The Aspect Ratio Constraint setting, set through the config tab, is now also applied every frame, so when the game overwrites this setting 
             with a camera cut during cutscenes, it's properly handled. 
    - Fixed: Added some more patterns for the pose function so the pose tool might be available now in more games (no, sorry not in Borderlands 4) 

v5.7.4:
    - Fixed: A bug was introduced in 5.7.3 causing postprocess settings to fail being applied 
    - Added: Added support for Silent Hill f, which uses a customized engine 

v5.7.3:
    - Added: Added Time of Day control for Borderlands 4 
    - Fixed: Fixed issue with Borderlands 4 having the main thread function execution code not always being activated or crash 

v5.7.2:
    - Fixed: (IGCS, Client, System) It could be that the setting value for Fast movement multiplier (and potentially some others) weren't registered with 
             the dll after the client had loaded the settings and sent over to the dll. 
    - Fixed: Unreal Engine 5.6 introduced new functions for the ConsoleVariable object which moved functions used by the UUU to a different location causing 
             the game to crash when you dumped CVars. 
    - Changed: The newly introduced engine version detection system has been adjusted so it can use its initial findings to obtain the real version from 
               the engine and adjust the version to use. 
    - Added: The UUU now tries to check if the elements in the GObjects array are of the expected size or that it should be using a different size. A few 
             games use smaller structure sizes, causing the UUU to crash the game as the UUU expects them to use the default structure size. 
    - Added: Added compatibility for Borderlands 4 

v5.7.1:
    - Fixed: Dumping cvars / objectsstore data from a game installed in a folder with non-ascii characters now work correctly 
    - Fixed: Added more patterns for the engine version so it's found in more games 
    - Changed: Added a probe function to determine which Unreal Engine version is compatible with the engine version used by the game in the case of when 
               the engine version isn't found. This should reliably (well, there are always exceptions of course... ) determine which version the UUU can 
               assume to work with the game so everything works and no crashes occur. 
    - Fixed: Added more patterns for objectsstore, hud toggle, black bars, pose function/offsets for newer engines 

v5.7.0:
    - Added: On the Recently Edited Bones tab, a button has been added to view the selected bone in the main tree 
    - Changed: Changed the rotation gizmo to only show the areas of the rotation circles which were active. The Imguizmo gizmo would react to hovering 
               over this part of the circle anyway which led to frustration why hovering parts of the rotation circles didn't do anything. The gizmo now 
               also causes less visual clutter 
    - Added: Light system in the overlay now allows attaching lights to an actor, manipulate lights in a group and save / load light presets. 
    - Fixed: Many tiny issues with the light editors were fixed 
    - Added: Several presets for lights were added to the main install. These are based on real-life photography tutorials. 

v5.6.5:
    - Fixed: Updated for Metal Gear Solid Delta: Snake Eater 

v5.6.4:
    - Fixed: UUU couldn't find the camera if the game was compiled using AVX2 instructions (e.g. Sword of the Sea). 

v5.6.3:
    - Changed: Removed the SET command enable hack, it rarely worked 
    - Added: Added lots of patterns for 5.5+ builds and 5.5+ debug builds. 
    - Changed: When the engine version isn't found because the game is a debug build, the UUU can now detect if the version is missing because of the exe 
               being a debug build and use the default maximum engine version as a proper fallback. This will avoid crashes in debug builds. 
    - Fixed: Pose editor didn't work on some games (like Grounded 2) 
    - Fixed: UE 5.5+ could have the version stored in a piece of code that wasn't caught by the UUU, causing it to fall back to UE 5.1 defaults which would 
             crash the game. 

v5.6.2:
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
    - Fixed: Added another pattern for the pose data interception so it's compatible with more games (E.g. Avowed latest patch) 
    - Added: Overlay: Added an option to the Actor manipulation tab in the overlay to keep changes made after the camera has been disabled. 
    - Added: Added additional validation for an unreal object being still active when it's e.g. reset by the UUU 

v5.6.1:
    - Fixed: (IGCS, Client, Hotsampling tab) It could be the Hotsampling tab didn't have the default aspect ratios displayed so only the native monitor 
             aspect ratio was added by default. 
    - Fixed: an attached light wasn't showing up as such on the client light list 

v5.6.0:
    - Fixed: (IGCS, Client, Hotsampling tab) The controls were configured wrong so the Refresh button wasn't properly aligned, causing wasted space next 
             to the splitter bar 
    - Added: The overlay now has a Light tab, which allows users to create and manipulate lights from the overlay. It also offers light rotation and location 
             manipulation through a gizmo, and offers light visualizers which are better than the engine arrow variant from older versions which weren't 
             always showing up. 
    - Added: Exposed additional light properties to the light editor in the overlay (not the client) 
    - Fixed: Copying a light didn't copy all properties of a light correctly 
    - Fixed: All properties of a light are now updated immediately from the client, instead of lagging behind. This greatly speeds up e.g. shadow related 
             properties like Contact Shadow Length and Shadow Bias among others. 
    - Fixed: When changing a gizmo setting in the overlay and not in the menu, it could be the setting wasn't saved to the ini file 

v5.5.2:
    - Changed: Added support for UE 5.6 
    - Fixed: The change added for 5.5.1 to instantiate the game specific cheat manager could backfire and cause crashes when a new level was loaded due 
             to the game not anticipating the cheat manager is live. They crash beause no code is in place to clean up the world reference. This change 
             has been reverted to the code that was in the UUU before so the cheat manager isn't really active. It'll be re-added later with an optional 
             button 
    - Fixed: Better pose editor compatibility with UE 5.5+ 
    - Fixed: Better compatibility with 5.4 games 

v5.5.1:
    - Changed: (IGCS, Hotsampling) Added a way to specify new aspect ratios and delete aspect ratios for the hotsampling resolution tree. The resulting 
               list of aspect ratios is persisted per client. 
    - Changed: If no cheat manager is set, the uuu can now recreate a new one and will use the game-specific variant, which should offer the functions 
               defined in these specific cheat managers to the console. 
    - Fixed: Pose tooling: If a root bone was changed in a component, it was always synced with all root bones of all other skeletal mesh components of 
             the actor, regarding of whether that root bone represented the same root. This could cause hair and other components become disaligned when 
             loading a pose or changing a root bone's angles or location. 

v5.5.0:
    - Fixed: If the fov was set to a very low value, the movement reduction factor wasn't properly calculated and it resulted to a faster movement again. 
    - Added: Selecting an actor or bone will optionally display an editor gizmo to rotate and move the actor or bone in the 3D world as an alternative 
             to the sliders in the overlay GUI. 
    - Fixed: Rotation sliders for actors now properly flip over after going to the edge of -180 or 180 degrees so it's no longer needed to move the slider 
             to the other side to keep on rotating 
    - Fixed: Skeletal Mesh Actors weren't always marked as movable when selected 
    - Fixed: Editing a character's location or bones no longer automatically resets the skeletal meshes/animation when the camera was disabled, if the 
             skeletal mesh/animations weren't changed. Previously this could lead to T-Posing characters on older UE5.x engines 

v5.4.12:
    - Fixed: Console commands meant for the active cheat manager could crash the game (like in the TES Oblivion remaster) as the UUU set the default cheat 
             manager as the active one 
    - Changed: If an existing cheat manager object is active, the UUU will now skip altering the SET command 
    - Changed: IGCS: increased number of recent resolutions on the hotsample tab to 15, made the entries of the list less high, added 6:7 

v5.4.11:
    - Fixed: Reference Skeleton caching could make the wrong choice when probing if the skeleton bones were stored with 4 bytes padding. 
    - Fixed: If the game has hidden values in between the time dilation values, the UUU potentially would use the wrong values to calculate the final time 
             dilation value also when slomo pause wasn't active, causing the game to pause. 
    - Fixed: If for some reason a mesh, animation or skeleton contains a reference to an invalid name (because of a misaligned pointer or other element), 
             the UUU no longer crashes but properly returns an "Invalid Name" string. 
    - Fixed: In the case if the character has multiple skeletal mesh components and a custom animation is active on one or more of them, switching between 
             the skeletal mesh components wouldn't select the active one again from the list, making it hard to navigate to a next animation in the llist 
             of animations. 
    - Fixed: Finally isolated the situation where expanding the Experimental Feature node for a selected Actor to select a different mesh or animation 
             could crash (invalid objects in the cache), and the UUU now caches meshes and animations every time the camera is enabled. As this is happening 
             in the background you won't notice this. 

v5.4.10:
    - Fixed: On some UE 5.4 game builds the pose tools didn't work as it couldn't find the code to intercept 
    - Fixed: IGCS: code refactoring of the quaternion to angle system accidentally removed the code to mark the camera as changed when the user tilted 
             the camera 90 degrees or reset the tilt/roll using the keyboard. 
    - Changed: A better player coordinate smoother which keeps a rolling average over the last 60 coordinates of the player and this seems to eliminate 
               any player stutter when a camera path is playing relative to the player 
    - Fixed: Implemented a better type cache to avoid rare crashes 
    - Fixed: Player coordinates weren't properly read which meant camera paths relative to the player could lead to being placed at the origin (0, 0, 0) 
    - Fixed: Resetting the skeletal mesh on an actor could set the original animation mode to an undefined state 
    - Changed: IGCS: Moved the Display Notifications checkbox to the configuration tab, and all new tool builds will have that from now on. 

v5.4.9:
    - Fixed: A better solution was implemented for Slomo pause so exceptions like the one for Avowed are no longer needed. This also corrects an issue 
             with quickly pausing/unpausing the game in Avowed leading to not being able to unpause without setting the gamespeed to 1.0. 
    - Fixed: In a rare case it could be that when clicking on the Actor manipulator tab in the overlay, the game would crash because the selected Skeletal 
             Mesh actor has invalid Mesh names. 
    - Fixed: The intensity slider for a light in the light editor wasn't reacting to holding shift to make it go slower. 

v5.4.8:
    - Fixed: Gamespeed / Slomo pause didn't work in Avowed, as it used the same custom code as seen in Hellblade 2. 

v5.4.7:
    - Fixed: In 5.4.6 a bug was introduced where rotating a bone in the bone editor would use an incomplete set of angles, causing the bone to snap to 
             a different position. 

v5.4.6:
    - Fixed: IGCS: Added more reliable code to prevent crashes when rendering the overlay while hotsampling 

v5.4.5:
    - Fixed: If the CVars in the ConsoleManager contained a non-ascii character in the helptext, the cvars output stopped at that cvar, even though the 
             code has support for unicode characters. 
    - Fixed: In some games the keybinding for opening the overlay wasn't taking effect as the client sent the setting value before the keybinding was registered. 
    - Fixed: A potential crash could occur when the pose editor was open and the user clicked an actor without a bone tree (e.g. a static mesh actor) 
    - Added: Ability to import a part of the bone tree from a saved pose file. This way you can e.g. import the face bones from a .uuupose file in the 
             current pose you have on an actor. 
    - Fixed: Resetting an actor after custom animations have been played are now properly handled in most cases where they weren't resetting before. It's 
             not 100% fail safe, but I hope it will work better in newer engines at least. Playing custom animations stays an experimental feature which 
             could cause T/A posing so use with care. 

v5.4.4:
    - Fixed: When selecting an actor, it could be in some games the UUU would crash due to memory corruption as it used an array that was too small for 
             some games. 

v5.4.3:
    - Fixed: The GUObjects array might not be found on engine builds v5.5+ 
    - Fixed: Added various patterns for UE 5.4/5 to make the UUU work better with UE 5.4+ games 
    - Fixed: The cvar dump now includes the values again for UE 5.4+ 
    - Fixed: CameraComponent aspect ratio constraint flag removal AOBs had an AOB that was too restrictive, so some games were still showing black bars 
             in non-16:9 ARs 
    - Changed: The default for Screen Space Reflections Max Roughness is now 1.0, the max value. 
    - Changed: All lights will now have their IntensityUnits set to Lumens and the maximum intensity values have been retweaked to be in line with that 
               change. This gives brighter lights in daylight lit areas in some games so they're actually visible. Before, the UUU would keep the game's 
               default (often 'UnitLess'), which was usually enough, but sometimes it made lights not bright enough outdoors. 
    - Fixed: The Light intensity max value/slider combination wasn't really setup to receive high values. It's now possible to specify a very high intensity 
             max value, e.g. 20,000,000,000, which allows daylight outdoor lights to be used. 

v5.4.2:
    - Fixed: Added a lot of additional patterns for UE5.4.x, so games with that engine build should now work better with the UUU 

v5.4.1:
    - Fixed: When you enabled pose editing on an actor and then either clicked 'Reset actor state' or disabled the camera, the morph targets weren't reset 
             properly 
    - Fixed: In some games cloning an actor could take more time than it would take the UUU to cache the clone's mesh and components, leading to the clone 
             being seen as not a full skeletal mesh component and thus that the pose tool wasn't available. 
    - Fixed: Added more patterns for Pose tool function interception so Silent Hill 2 and probably other games will now work 
    - Fixed: Color information in post-processing presets wasn't loaded properly, resulting in the wrong values being applied when the preset was activated 

v5.4.0:
    - Fixed: Added more patterns for GEngine/Objectsstore and engine version discovery in 5.4+ based games 
    - Fixed: Clicking on an actor in the world no longer will select actors that are 'hidden'. 
    - Fixed: Cloning a character will now set the clone's skin/skeletal mesh properly 
    - Added: Morph target support in the pose editor for games that support morph targets. Morph targets are specific changes to parts of the skeletal 
             mesh. Changes made to these are saved with a pose. 
    - Added: Sub-component support per actor for posing, including playing animations on a sub component (e.g. the face). 
    - Changed: More animations are visible in the drop down list for custom animations to play on a mesh and they're now sorted by name 
    - Fixed: Saving a pose now properly generates a filename for the first time and navigating a to a different folder no longer clears that initial filename 
    - Fixed: Added a better generic pattern for obtaining the functions needed for the pose editor, so more games should now have pose editor support (e.g. 
             UE5.4+ games) 
    - Fixed: The Field of View is now no longer stuck in most games to the FoV you set it to when the camera is enabled. 
    - Fixed: The pose tool didn't work on UE 5.4+ due to a change in how the engine reports which object was clicked. 
    - Fixed: HUD toggle wasn't always fully found in UE 5.4+ games and sometimes reported as 'not being available' while the part that was found worked 
             ok. 
    - Fixed: Some UE 5.0 games crashed in the UUU due to missing offsets as UE5.0 was never officially released and the UUU assumed UE 5.1 in the case 
             a game would use 5.0 

v5.3.2:
    - Fixed: When playing back a camera path, a roll/tilt angle wasn't properly set 

v5.3.1:
    - Fixed: In a rare occasion it was possible to have the pose editor open when the camera was disabled, which suggested the user could change the pose 
             which wasn't the case 
    - Changed: UUU 4/5: bumped up the min/max delta for actor movement from 100m to 500m 
    - Fixed: Unpausing NPCs could potentially crash the game if the engine had garbage collected one or more NPCs that were paused 

v5.3.0:
    - Added: Pose editor in games that are supported for this feature; you can manipulate any bone in an actor (e.g. your character, an enemy) to pose 
             them how you like it. 
    - Fixed: Better support for Black Myth: Wukong, it now won't crash when you select an actor in the scene. HUD toggle won't work, you have to use shader 
             toggler for full HUD toggle in this game. 
    - Fixed: Additional black bar removal code for UE5.0 added 
    - Fixed: Much better selection code for selecting actors in a scene. 

v5.2.3:
    - Fixed: Small fix to remove a mouse pointer issue when the overlay is visible: the mouse wasn't movable outside a small area in the game window 

v5.2.2:
    - Fixed: the selected actor was always scrolled into view and therefore it made scrolling the whole window impossible at times 
    - Fixed: extra hud toggle patterns for UE 5.3.x 
    - Added: added a checkbox for whether the UUU should use a low-level UWorld::IsPaused hack (default) or use the default engine pause. The default engine 
             pause might crash or bring up a pause menu, hence the low-level route is the default. (In v4 this was also the case). The UUU will also use 
             the default engine pause if the UWorld::IsPaused function isn't found. 

v5.2.1:
    - Added: Added a key binding editor for toggling the in-game overlay 
    - Added: Added a setting on the IGCSClient Configuration tab for controlling the aspect ratio axis constraint, which is which field of view angle (vertical 
             or horizontal) is kept when the aspect ratio changes (which e.g. happens when the letter/pillarboxes are removed or when you change the aspect 
             ratio of your window). In earlier versions, the UUU decided by itself what was best, but this could lead to zoomed in images when the aspect 
             ratio constraint was removed. 

v5.2.0:
    - Added: In-game overlay for actor selection and manipulation, which allows you to clone/rotate/move any asset in a game world, as well as change the 
             mesh and animation on some skeletal mesh actors (e.g. enemies). Open the in-game overlay with Ctrl+<key to enable the camera>, so by default 
             Ctrl-Insert. It's mandatory to read the updated documentation for this feature! 

v5.1.8:
    - Fixed: In some UE5.x games, the black bar removal code could match with a pattern that had the wrong change assigned to it, so it would cause flickering 
             black bars when moving the camera. 
    - Fixed: IGCS: Fixed an issue with the deadzone curve code for a gamepad where small trigger values would result in negative values being reported 
             causing up/down movement to go briefly in the opposite direction than intended. 
    - Changed: Finetuned the default movement/rotation/fov speeds for UE v5, as the defaults appeared to be off for most games, especially after moving 
               to double precision values internally. 
    - Added: IGCS: Holding Ctrl on keyboard or X on gamepad while changing the FoV will now make the FoV change 90% slower so it's easier to put the FoV 
             at the correct value 
    - Changed: The camera interception has been extended so the tools now also try to obtain the camera from the PlayerCameraManager, which might help 
               with games which have a custom camera pipeline which causes the existing camera interception code in the UUU not to be able to grab the 
               camera. 

v5.1.7:
    - Added: In UE 5.3 the Field of View (FoV) isn't kept the same when the aspect ratio is changed. This caused problems when removing the aspect ratio 
             constraints (letterboxing), as the game zoomed in and thus lost parts of the screen left/right. An engine variable is set by the UUU to correct 
             this, making removing black bars in games no longer zoom in the game (e.g. Hellblade 2) 

v5.1.6:
    - Added: UUU v5 now supports Senua's Saga: Hellblade 2. It's required to follow certain steps and to specify certain commands on the console to get 
             the best experience. Please see https://opm.fransbouma.com/uuuv5.htm#games-that-work-with-the-uuu for details regarding this game (and also 
             specifics for other games, if needed). 

v5.1.5:
    - Added: More patterns for SCompoundWidget::OnPaint and black bar removal for certain games. 

v5.1.4:
    - Added: More patterns to find the GObjects array so it should be compatible with more UE5 games now (e.g. 5.3 builds). 
    - Added: Unreal Engine 5.3 support 
    - Added: More patterns for other elements of the engine so the UUU is compatible with more games, already released and upcoming. 

v5.1.3:
    - Fixed: If the camera was enabled but no camera path was playing, pressing F8 (stop camera path playback) would cause the postprocessing settings 
             to be reset as if a camera path was playing. 
    - Added: If the dll was loaded from a path which contained non-ascii characters, the injection would fail with a cryptic error. It will now properly 
             load the dll from a path with non-ascii characters. 

v5.1.2:
    - Added: 3D visualizers in-game for Lights. You can toggle them on/off (default off) using a button on the lights tab and using a keyboard shortcut 
             (default ';', but bind a different key you like to use instead if ';' isn't suitable for you). Spotlights now have an arrow starting at the 
             spotlight location pointing in the direction the spotlight is shining at, pointlights get a 6 arrow object at the location of the light. The 
             visualizers are drawn in the color of the light. 

v5.1.1:
    - Added: Support for Tekken 8, some more patterns to match aspect ratio constraining locations. (Black bars). 
    - Added: Made the light editor's max intensity slider work with shift and scrollwheel now so it's easier to tweak the maximum. 
    - Added: A couple more settings to the light editor like light falloff exponent 

v5.1.0:
    - Added: Reworked the postprocessing tab, there are now over 96 settings to tweak, complete with presets (I included a couple to get you started). 
             I've included all settings from the Unreal Engine post-processing volume that made sense. It greatly enhances tweakability of games. Please 
             see the updated documentation at https://opm.fransbouma.com/uuuv5.htm for details. 

v5.0.8:
    - Added: Added the Light's Shadow Resolution Scale slider back. It was removed early in 5.0 as the setting didn't seem to do anything but that was 
             a mistake, it does affect light resolution. 

v5.0.7:
    - Fixed: UObject::ProcessEvent used a pattern which could match with the wrong function, causing lights / camera enable to crash the game.This happens 
             with UE5.2+ games, like Robocop, Lords of the Fallen and others. 
    - Fixed: Bug in the UUU black bars removal code actually introduced constrained aspect ratio limitation in some games, e.g. Lords of the Fallen. 

v5.0.6:
    - Fixed: The FoV and camera coordinates weren't reported correctly in the IGCSConnecto 
    - Fixed: Dumping cvars could crash due to illegal utf8 characters being written to the json file. 
    - Fixed: The quaternion to roll angle calculation didn't negate the value so API calls to step the camera in a situation where the camera had any tilt 
             caused misalignment. E.g. focusing in IGCS DoF with the UUU v5 was difficult if there was any tilt/roll involved. 
    - Changed: Switched the light intensity units to Lumens for new lights and changed the default max from 15000 to 1500. This will give brighter lights 
               even in worlds with strong sunlight or Lumen lit environments. 

v5.0.5:
    - Added: Added a previous/next light button pair at the top of the Light editor window to cycle through the lights without the necessity to go back 
             to the main light list. 
    - Added: Better HUD toggle in case the existing one doesn't work properly. 

v5.0.4:
    - Fixed: On modular builds and some other games where the ConsoleManager wasn't found, the UUU would crash as it didn't properly handle the situation 
             when the console manager wasn't found. 

v5.0.3:
    - Added: Cvars are now also dumped in a .json file, additionally to the .txt file the UUU already wrote to. 
    - Added: Readonly CVars and commands are now unlocked without dumping them to a file. 
    - Added: More blackbar removal code (Now works in e.g. Jusant) 

v5.0.2:
    - Added: On the Available Features tab, you can now click 'Dump CVars' (when supported by the game) and it'll dump a file with all the cvars/commands 
             you can use on the console, with the help text and the type + current value of the variable. This file is placed next to the objects dump 
             file you can create on the same tab, using the filename "UUU_CVarsDump.txt" 
    - Fixed: Camera movement shake strength was affected by how high the movement speed was set. This isn't the case anymore. 

v5.0.1:
    - Added: Ability to configure which gamepad trigger is used for moving camera up/down 
    - Added: Ability to configure which gamepad stick is used for rotating/moving the camera (for left-handed users). 
    - Added: Keybinding for appending a new node after the active node on the current path 
    - Added: Keybinding for deleting the current path 
    - Added: Keybinding for deleting the active node on the current path 
    - Added: Shift / Shift+Ctrl are now usable on the sliders to have them move slower and even more slower 
    - Added: The mousewheel can now be used on the sliders to move the value. Using Shift or Shift+Ctrl makes the slider move slower and even slower. 

v5.0.0:
    - General: First public v5 release. 


v5.1.5:
	ADDED: More patterns for SCompoundWidget::OnPaint and black bar removal for certain games. 
v5.1.4:
	ADDED: More patterns to find the GObjects array so it should be compatible with more UE5 games now (e.g. 5.3 builds).
	ADDED: Unreal Engine 5.3 support
	ADDED: More patterns for other elements of the engine so the UUU is compatible with more games, already released and upcoming. 
v5.1.3: 
	FIXED: If the dll was loaded from a path which contained non-ascii characters, the injection would fail with a cryptic error. 
	       It will now properly load the dll from a path with non-ascii characters. 
	FIXED: If the camera was enabled but no camera path was playing, pressing F8 (stop camera path playback) would cause the postprocessing settings to be reset
	       as if a camera path was playing. 
v5.1.2:
	ADDED: 3D visualizers in-game for Lights. You can toggle them on/off (default off) using a button on the lights tab and using a 
	       keyboard shortcut (default ';', but bind a different key you like to use instead if ';' isn't suitable for you). Spotlights now have an arrow starting
		   at the spotlight location pointing in the direction the spotlight is shining at, pointlights get a 6 arrow object at the location of the light. The
		   visualizers are drawn in the color of the light.
v5.1.1: 
	ADDED: Support for Tekken 8, some more patterns to match aspect ratio constraining locations. (Black bars). 
	ADDED: Made the light editor's max intensity slider work with shift and scrollwheel now so it's easier to tweak the maximum.
	ADDED: A couple more settings to the light editor like light falloff exponent
v5.1.0:
	ADDED: Reworked the postprocessing tab, there are now over 96 settings to tweak, complete with presets (I included a couple to get you started). I've included all
	       settings from the Unreal Engine post-processing volume that made sense. It greatly enhances tweakability of games. Please see the updated documentation at
		   https://opm.fransbouma.com/uuuv5.htm for details. 
v5.0.8:
	ADDED: Added the Light's Shadow Resolution Scale slider back. It was removed early in 5.0 as the setting didn't seem to do anything but 
	       that was a mistake, it does affect light resolution.
v5.0.7:
	FIXED: UObject::ProcessEvent used a pattern which could match with the wrong function, causing lights / camera enable to crash the game. 
	       This happens with UE5.2+ games, like Robocop, Lords of the Fallen and others.
    FIXED: Bug in the UUU black bars removal code actually introduced constrained aspect ratio limitation in some games, e.g. Lords of the Fallen.
v5.0.6: 
	FIXED: The FoV and camera coordinates weren't reported correctly in the IGCSConnector
	FIXED: Dumping cvars could crash due to illegal utf8 characters being written to the json file.
	FIXED: The quaternion to roll angle calculation didn't negate the value so API calls to step the camera in a situation where the camera had any tilt
	       caused misalignment. E.g. focusing in IGCS DoF with the UUU v5 was difficult if there was any tilt/roll involved. 
	CHANGED: Switched the light intensity units to Lumens for new lights and changed the default max from 15000 to 1500. This will give brighter lights even in worlds 
	         with strong sunlight or Lumen lit environments.
v5.0.5:
	ADDED: Added a previous/next light button pair at the top of the Light editor window to cycle through the lights without the necessity to go back to the main light list.
	ADDED: Better HUD toggle in case the existing one doesn't work properly.
v5.0.4:
	FIXED: On modular builds and some other games where the ConsoleManager wasn't found, the UUU would crash as it didn't properly handle the situation 
           when the console manager wasn't found. 
v5.0.3:
	ADDED: Cvars are now also dumped in a .json file, additionally to the .txt file the UUU already wrote to.
	ADDED: Readonly CVars and commands are now unlocked without dumping them to a file.
	ADDED: More blackbar removal code (Now works in e.g. Jusant)
v5.0.2:
	FIXED: Camera movement shake strength was affected by how high the movement speed was set. This isn't the case anymore. 
	ADDED: On the Available Features tab, you can now click 'Dump CVars' (when supported by the game) and it'll dump a file with all the cvars/commands you can 
	       use on the console, with the help text and the type + current value of the variable. This file is placed next to the objects dump file
		   you can create on the same tab, using the filename "UUU_CVarsDump.txt"
v5.0.1: 
	ADDED: Ability to configure which gamepad trigger is used for moving camera up/down
	ADDED: Ability to configure which gamepad stick is used for rotating/moving the camera (for left-handed users).
	ADDED: Keybinding for appending a new node after the active node on the current path 
	ADDED: Keybinding for deleting the current path
	ADDED: Keybinding for deleting the active node on the current path
	ADDED: Shift / Shift+Ctrl are now usable on the sliders to have them move slower and even more slower
	ADDED: The mousewheel can now be used on the sliders to move the value. Using Shift or Shift+Ctrl makes the slider move slower and even slower.
v5.0.0: First public v5 release. 

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
To take screenshots at higher resolutions than your regular gaming resolution, run the game in windowed mode,  unless it's been specified in the supported game list
in https://opm.fransbouma.com/uuuv5.htm you need to use a different mode (e.g. borderless windowed, or fullscreen).
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
This is the UUU version for games using Unreal Engine 5.1 or higher. As Unreal Engine 5.1 is rather new, if you get lots of errors, 
it might very well be the game you're using the UUU v5 with isn't using Unreal Engine 5 but Unreal Engine 4 (or not using Unreal Engine at all!). 
So be sure the game uses Unreal Engine 5 when using this UUU version.

If you get AOB errors when injecting the dll, it might be the engine's code hasn't been fully initialized yet and AOB scanning can't
find it. Simply load a level and try again by pressing CTRL+END. 

The built-in HUD toggle might not work if the HUD is built with a custom HUD system like scaleform. In that case the hud toggle won't hide
the HUD. If that's the case, you might want to try 'showhud 0' (without the quotes) to hide the hud and 'showhud 1' to show it again in the console.
This might not always work, it depends per game. 

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