# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

"""Chaînes anglaises de l'interface -- même clés que `strings.STRINGS`
(français, source de référence), mêmes variables `{…}` dans chaque
modèle (vérifié par `tests/test_gui_strings.py`).

Une clé absente ici retombe sur le français (`strings.tr`), jamais sur
une chaîne vide ni une exception -- mais le test exige qu'il n'en manque
aucune. Même vocabulaire sans jargon qu'en français (§5) : « your SD
card », « your games », jamais « block device » ni « partition »."""

from __future__ import annotations

STRINGS_EN = {
    "app_title": "R36S Studio",
    "splash_starting": "Starting… looking for your SD card",
    "home_title": "What do you want to do?",
    "home_refresh": "Refresh",
    "home_assisted_mode_button": "Guided mode",
    "home_consoles_diverses_button": "Other consoles",
    "home_android_button": "Android console",
    "home_step_a_title": "A. Copy BOOT from the original SD card",
    "home_step_a_desc": "Saves the screen and settings of your old card to your computer.",
    "home_step_b_title": "B. Copy EASYROMS from the original SD card",
    "home_step_b_desc": "Saves your games and saves from the old card to your computer.",
    "home_step_c_title": "C. Flash ArkOS to the new SD card",
    "home_step_c_desc": "Writes the system to your new card.",
    "home_step_d_title": "D. Copy BOOT to the new SD card",
    "home_step_d_desc": "Puts the original screen and settings back on the new card.",
    "home_step_e_title": "E. Copy EASYROMS to the new SD card",
    "home_step_e_desc": "Puts your games and saves back on the new card.",
    "home_step_f_title": "F. Safely eject the SD card",
    "home_step_f_desc": "Unmounts the card so it can be removed without risk.",
    "home_backup_separator": "To be safe",
    "home_tile_backup": "Back up a full image of my card",
    "home_tile_backup_desc": "Saves the current contents of your SD card to a file, just in case.",
    "home_tile_backup_system": "Back up my system without the games",
    "home_tile_backup_system_desc": (
        "Saves the screen and settings of your card, without your games — "
        "a much smaller file than a full backup."
    ),
    "home_tile_reset_card": "Reset the card",
    "home_tile_reset_card_desc": (
        "Erases everything on this card and turns it back into a single normal storage space — "
        "useful after trying several firmwares."
    ),
    "home_help": "Help: allow access to the card (Mac)",
    "home_tile_web": "Web",
    "home_tile_web_desc": "Opens the website in your browser.",
    "home_tools_separator": "Tools",
    "home_tile_find_duplicates": "Find duplicates",
    "home_tile_find_duplicates_desc": "Finds duplicate games in a folder and sets them aside, without deleting anything.",
    "home_tile_sort_games": "Sort my games",
    "home_tile_sort_games_desc": "Sorts a folder of mixed games into one folder per console.",
    "status_available": "Available",
    "status_done": "Already done",
    "status_not_relevant": "Not relevant for this card",
    "status_platform_limited": "PC or Linux",
    "status_system_incompatible": "Not applicable — ROCKNIX card",
    "home_banner_line_device": "{display} — {size_go:.1f} GB",
    "home_banner_state_arkos": "ArkOS card recognized",
    "home_banner_state_unprepared": "Card not prepared",
    "home_banner_state_none": "No card detected yet",
    "assisted_prepare_button": "Prepare my card automatically",
    "assisted_expert_mode_button": "Expert mode",
    "assisted_backup_system_button": "Back up my system without the games",
    "assisted_tile_prepare": "Prepare my card",
    "assisted_tile_prepare_desc": "Full copy from the old card to the new one, step by step.",
    "assisted_tile_identify": "Identify my console",
    "assisted_tile_backup": "Back up my card",
    "assisted_tile_eject": "Eject the card",
    "assisted_tile_help": "Help",
    "assisted_brand_subtitle": "Choose what you want to do with your SD card.",
    "assisted_section_label": "To get started",
    "about_title": "About R36S Studio",
    "about_orientation": (
        "Each tile on the home screen is an action on your SD card. Plug in your card: the app "
        "detects what is on it and suggests the relevant action with a badge (available, already "
        "done, not relevant for this card). Nothing ever happens until you click, and any action "
        "that erases something asks you explicitly before it starts."
    ),
    "about_close": "Close",
    "identify_result_title": "Your console",
    "identify_result_board": "Detected identifier: {board}",
    "identify_result_catalog_button": "See the console catalog",
    "identify_result_clone_warning": (
        "This card seems to come from a clone console (different hardware from a standard "
        "R36S/R35S). Systems made for the standard R36S may not start on it. dArkOS and EmuELEC "
        "say they support these consoles; EmuELEC has been checked on a real clone console."
    ),
    "identify_failed_mount_failed": "Could not read the card's system. Unplug it, plug it back in, then try again.",
    "identify_failed_no_dtb_found": (
        "No model information found on this card -- this is normal for a card that was just flashed."
    ),
    "identify_failed_all_dtb_invalid": "The model information on this card is unreadable or corrupted.",
    "doublons_back_button": "Back",
    "doublons_folder_title": "Choose a folder",
    "doublons_folder_hint": "Choose the folder to scan -- on your computer, an SD card or an external drive.",
    "doublons_folder_no_shortcuts": "No card or removable drive detected yet.",
    "doublons_resume_button": "Resume the last scan",
    "doublons_resume_info": "{folder} -- scanned on {date}",
    "doublons_resume_files_removed_notice": (
        "{count} file(s) removed from the results -- changed or deleted since the last scan."
    ),
    "doublons_browse_button": "Browse…",
    "doublons_options_title": "OPTIONS",
    "doublons_simulation_checkbox": "Simulate without moving anything",
    "doublons_ignored_folders_title": "Ignored folders:",
    "doublons_scan_progress_title": "Scanning",
    "doublons_scan_progress_count": "{count} file(s) scanned",
    "doublons_scan_cancel_button": "Cancel",
    "doublons_move_progress_title": "Moving",
    "doublons_move_progress_count": "{done} / {total} file(s)",
    "doublons_risk_title": "This folder may take a while to scan",
    "doublons_risk_cancel": "Cancel",
    "doublons_risk_continue": "Continue",
    "doublons_risk_filesystem_root": (
        "You chose the whole root of a drive -- the scan may take a very long time and go through "
        "folders unrelated to your games. Continue anyway?"
    ),
    "doublons_risk_whole_user_folder": (
        "You chose a whole personal folder rather than a specific games folder -- the scan may take "
        "a very long time. Continue anyway?"
    ),
    "doublons_risk_large_folder": (
        "This folder already contains more than 200,000 files and the scan is still going -- it may "
        "take a while. Continue?"
    ),
    "doublons_results_title": "Duplicates found",
    "doublons_undo_button": "Undo all",
    "doublons_undo_conflicts_warning": (
        "{count} file(s) could not be restored automatically -- check the contents of the _doublons/ folder."
    ),
    "doublons_export_button": "Export the report",
    "doublons_destination_label": "Destination:",
    "doublons_destination_change_button": "Change…",
    "doublons_destination_cross_volume_warning": (
        "Destination on another drive: the files will be copied, then deleted from the source (slower)."
    ),
    "doublons_destination_space_warning": (
        "Space available at the destination: {available} -- may not be enough for this move."
    ),
    "doublons_destination_fat_warning": (
        "The destination is formatted as FAT, which cannot hold files larger than 4 GB -- {count} "
        "selected file(s) are larger than that and cannot be moved."
    ),
    "doublons_simulation_banner": "Simulation mode on -- nothing will be moved.",
    "doublons_auto_selection_banner": "Automatic selection: check it before moving.",
    "doublons_select_all_button": "Check all",
    "doublons_select_none_button": "Uncheck all",
    "doublons_keep_french_european_button": "Keep only the French and European versions",
    "doublons_summary": (
        "{files} file(s) scanned -- {exact} group(s) of identical copies, {versions} group(s) of "
        "different versions."
    ),
    "doublons_empty": "No duplicates found.",
    "doublons_selection_summary": "{count} file(s) selected -- {size} can be freed",
    "doublons_move_all_button": "Set aside the {count} selected files ({size})",
    "doublons_group_exact_title": "Identical copies",
    "doublons_exact_group_hash_label": "SHA-256: {hash}",
    "doublons_exact_group_identical_notice": (
        "Exactly the same content (same SHA-256 fingerprint), despite different names."
    ),
    "doublons_move_this_one": "Set this one aside",
    "doublons_move_selected_button": "Set the selection aside",
    "doublons_excluded_title": "Excluded groups -- linked file not found",
    "doublons_excluded_entry": "{manifest}: {missing} not found",
    "doublons_confirm_title": "Set these duplicates aside?",
    "doublons_confirm_message": (
        "{count} file(s) ({size}) will be moved to a _doublons/ folder -- not deleted, you can put "
        "them back later if needed."
    ),
    "doublons_confirm_message_simulation": (
        "Simulation: {count} file(s) ({size}) would be moved to a _doublons/ folder -- nothing will "
        "actually be touched."
    ),
    "doublons_confirm_button": "Set aside",
    "doublons_confirm_button_simulation": "Simulate",
    "doublons_confirm_cancel": "Cancel",
    "doublons_undo_confirm_title": "Undo all?",
    "doublons_undo_confirm_message": "All the files moved to _doublons/ will be put back where they were.",
    "doublons_undo_confirm_button": "Undo all",
    "doublons_file_error_title": "Could not move this file",
    "doublons_file_error_message": "{path}\n\n{reason}\n\nSkip this file and continue with the next ones?",
    "doublons_file_error_message_copy_succeeded": (
        "{path}\n\nThe copy succeeded, but the original could not be deleted: {reason}\n\n"
        "Skip this file and continue with the next ones?"
    ),
    "doublons_move_reason_access_denied": "access denied.",
    "doublons_move_reason_read_only": "the destination is write-protected (read-only card or drive).",
    "doublons_move_reason_path_too_long": "the path is too long.",
    "doublons_move_reason_drive_removed": "the drive seems to have been unplugged or is no longer accessible.",
    "doublons_move_reason_insufficient_space": "not enough space on the destination drive.",
    "doublons_move_reason_unknown": "unknown reason.",
    "doublons_partial_move_completed": (
        "{moved} file(s) moved, {skipped} skipped after a failure -- see the log for details."
    ),
    "assisted_backup_system_running_title": "Backing up the system",
    "assisted_backup_system_running_instruction": "Don't unplug your card during the backup.",
    "assisted_backup_system_done_title": "Backup complete",
    "assisted_backup_system_done_instruction": "What do you want to do now?",
    "assisted_backup_running_title": "Backing up the card",
    "assisted_backup_running_instruction": "Don't unplug your card during the backup.",
    "assisted_backup_done_title": "Backup complete",
    "assisted_backup_done_instruction": "What do you want to do now?",
    "assisted_flash_running_title": "Installing the system",
    "assisted_flash_running_instruction": "Don't unplug your card during the installation.",
    "assisted_copy_games_running_title": "Copying the games",
    "assisted_copy_games_running_instruction": "Don't unplug your card during the copy.",
    "assisted_copy_games_done_title": "Games copied",
    "assisted_copy_games_done_instruction": "What do you want to do now?",
    "assisted_reset_card_running_title": "Resetting the card",
    "assisted_reset_card_running_instruction": "Don't unplug your card during the operation.",
    "assisted_reset_card_done_title": "Card reset",
    "assisted_reset_card_done_instruction": "What do you want to do now?",
    "assisted_eject_running_title": "Ejecting the card",
    "assisted_eject_running_instruction": "Don't unplug your card.",
    "assisted_eject_done_title": "Card ejected",
    "assisted_eject_done_instruction": "You can safely remove your card.",
    "assisted_prepare_card_button": "Prepare a card with this backup",
    "assisted_return_home_button": "Back to home",
    "assisted_prepare_card_choose_device_title": "Choose the card to prepare",
    "assisted_prepare_card_choose_device_instruction": (
        "Plug in the new SD card you want to prepare with this backup."
    ),
    "assisted_prepare_card_done_title": "Card prepared",
    "assisted_prepare_card_done_instruction": "What do you want to do now?",
    "wizard_continue": "Continue",
    "wizard_resume": "Resume",
    "wizard_cancel": "Cancel",
    "wizard_status_waiting": "Waiting for your card…",
    "wizard_status_device_found": "Card recognized: {display}",
    "wizard_status_same_card": "This is the same card — insert the new card, not the old one.",
    "wizard_status_confirmation_needed": "Confirmation needed — check the window that opened.",
    "wizard_status_multiple_candidates": "Several cards detected — choose the right one.",
    "wizard_diagnostic_summary": "Detection: {accepted} card(s) kept, {rejected} set aside",
    "wizard_poll_started": "Automatic card polling started.",
    "wizard_poll_stopped": "Automatic card polling stopped.",
    "wizard_poll_stall_detected": "Automatic card polling seemed stuck for {seconds} s — restarted.",
    "wizard_step1_title": "1. Insert your original SD card",
    "wizard_step1_instruction": "Plug your console's old SD card into your computer.",
    "wizard_step2_title": "2. Copying your card to the computer",
    "wizard_step2_instruction": "Choose what you want to back up, then it is saved to your computer.",
    "wizard_backup_kind_title": "What do you want to back up?",
    "wizard_backup_kind_full": "Full copy",
    "wizard_backup_kind_full_desc": "The screen, the settings and all your games. Up to about {size}.",
    "wizard_backup_kind_system": "System only, without the games",
    "wizard_backup_kind_system_desc": "Only the screen and the settings — a much smaller file.",
    "wizard_create_image_size_hint": "Maximum size of the copy: about {size}.",
    "reset_card_label_title": "Card name",
    "reset_card_label_instruction": (
        "Choose the name this card will show once it is empty — you can keep this one."
    ),
    "reset_card_label_continue": "Continue",
    "reset_card_filesystem_title": "How should the card be formatted?",
    "reset_card_filesystem_exfat": "exFAT — recommended",
    "reset_card_filesystem_exfat_desc": "Accepts large files. Works with most recent consoles.",
    "reset_card_filesystem_fat32": "FAT32",
    "reset_card_filesystem_fat32_desc": "For older consoles that cannot read exFAT.",
    "reset_card_filesystem_fat32_note": "With FAT32, a single file cannot be larger than 4 GB.",
    "reset_card_fat32_impossible_warning": "FAT32 is not possible on a card this small. Choose exFAT instead.",
    "wizard_image_created_log": "Image created: {path}",
    "wizard_step3_title": "3. Insert your new card",
    "wizard_step3_instruction": "Now plug in the new card to prepare.",
    "wizard_ejecting_source": "Ejecting your original card…",
    "wizard_source_ejected": "You can now safely remove your original card.",
    "wizard_step4_title": "4. Installing on your new card",
    "wizard_step4_instruction": "Your backup is being installed on your new card.",
    "wizard_step5_title": "5. Ejecting",
    "wizard_step5_instruction": "Your new card is being safely ejected — it is ready.",
    "wizard_finished": "Your card is ready! You can remove it and put it in your console.",
    "wizard_archive_destination_log": "Destination: {path}",
    "file_releases_button": "See the versions available online",
    "firmware_status_maintained": "Maintained",
    "firmware_status_archived": "Archived",
    "firmware_status_experimental": "Experimental",
    "file_firmware_arkos_title": "ArkOS / dArkOS",
    "file_firmware_arkos_desc": (
        "The reference system for the R36S, which also says it supports many clone consoles. "
        "Updated by the community (dArkOS)."
    ),
    "file_firmware_rocknix_title": "ROCKNIX",
    "file_firmware_rocknix_desc": "A more recent system, with built-in game transfer over USB.",
    "file_firmware_emuelec_title": "EmuELEC",
    "file_firmware_emuelec_desc": "Another option for clone consoles, already tested successfully on one of them.",
    "file_firmware_amberelec_title": "AmberELEC",
    "file_firmware_amberelec_desc": (
        "Made for the same chip family (RK3326) as the R36S; R36S compatibility not officially confirmed."
    ),
    "file_firmware_minui_title": "MinUI",
    "file_firmware_minui_desc": "Minimalist interface. Community port for the R36S, separate from the official project.",
    "file_firmware_r36droid_title": "R36Droid (Android)",
    "file_firmware_r36droid_desc": "Community port of Android (LineageOS) for R36S/RK3326.",
    "file_firmware_andr36oid_title": "andr36oid (Android)",
    "file_firmware_andr36oid_desc": "Another community port of Android (LineageOS) for R36S/RK3326.",
    "flash_android_format_prompt_warning": (
        "Windows will probably offer to format your card (\"You need to format the disk…\"), "
        "sometimes several times in a row — click Cancel every time, this is normal: Windows simply "
        "cannot read the Android system you just installed, it is not a problem with your card."
    ),
    "flash_format_prompt_warning_generic": "Windows may offer to format the card — click Cancel, this is normal.",
    "flash_android_panel_mismatch_warning": (
        "If the screen stays black or frozen at startup, open the card's BOOT drive (Windows "
        "shows it as a separate drive named BOOT): a \"Panels\" folder contains one subfolder per "
        "screen type, each with .dtb files to copy to the root of the BOOT drive to change the "
        "screen. It sometimes takes several tries — and there is no "
        "guarantee that one of these screens matches your console."
    ),
    "file_manual_download_hint": (
        "The downloaded file may be an archive (.7z, .zip…): extract it first if needed, then "
        "choose here the .img file it contains."
    ),
    "file_rocknix_download_button": "Download the latest version",
    "rocknix_variant_title": "Choose a version of ROCKNIX",
    "rocknix_variant_hint": (
        "Several versions are available. If you don't know which one to choose, take the first one in the list."
    ),
    "device_title": "Choose your SD card",
    "device_refresh": "Refresh",
    "device_empty": "No SD card detected. Plug it in, then click Refresh.",
    "device_next": "Next",
    "device_back": "Back",
    "file_title_backup": "Where should the backup be saved?",
    "file_title_backup_system": "Where should the system backup be saved?",
    "file_title_flash": "Choose the image file",
    "file_title_extract_boot": "Where should the backup of the original screen be saved?",
    "file_title_extract_easyroms": "Where should the games backup be saved?",
    "file_title_inject_boot": "Choose the backup of the original screen to put back",
    "file_title_copy_games": "Choose the games backup to put back",
    "file_archive_empty": "No backup found on this computer. Use \"Browse…\" to choose one.",
    "file_destination_hint": "A dated folder will be created automatically inside this location.",
    "file_browse": "Browse…",
    "file_next": "Next",
    "file_back": "Back",
    "confirm_title": "Warning",
    "confirm_checkbox": "I understand that all the data on this card will be erased",
    "confirm_erase": "All the data on \"{display}\" ({size_go:.1f} GB) will be permanently erased.",
    "confirm_go": "Erase and write",
    "confirm_cancel": "Cancel",
    "same_card_unverified_title": "Confirm that this is a different card",
    "same_card_unverified_message": (
        "Make sure you have removed the original card: writing to it by mistake would destroy the "
        "only working copy of your console.\n\n"
        "Cannot automatically verify that \"{display}\" ({size_go:.1f} GB) really is a different "
        "card from the original one — it has no readable system to compare its contents, and the "
        "size alone is not enough to prove it. If it is a new or blank card, this is normal."
    ),
    "same_card_unverified_checkbox": "I confirm that this really is a different card from the original one.",
    "same_card_unverified_confirm": "Continue",
    "log_header_idle": "Waiting",
    "log_header_active": "ACTIVE OPERATION — {title}",
    "execute_title_backup": "Backing up…",
    "execute_title_backup_system": "Backing up the system…",
    "execute_title_flash": "Writing…",
    "execute_title_extract_boot": "Copying the original screen…",
    "execute_title_extract_easyroms": "Copying the games…",
    "execute_title_inject_boot": "Putting the original screen back…",
    "execute_title_copy_games": "Copying the games…",
    "execute_title_reset_card": "Resetting the card…",
    "execute_title_list_rocknix": "Looking for ROCKNIX versions online…",
    "execute_title_download_rocknix": "Downloading ROCKNIX…",
    "rocknix_download_success": "The latest version of ROCKNIX has been downloaded: {path}",
    "execute_cancel": "Cancel",
    "execute_speed": "{speed:.1f} MB/s",
    "execute_eta": "Estimated time left: {eta}",
    "execute_eta_unknown": "Estimated time left: —",
    "result_eject": "Eject the card",
    "result_archive_created": "Saved in: {path} — Size: {size}",
    "result_archive_source": "From: {path}",
    "help_title": "Allow access to your SD card",
    "help_body": (
        "On a Mac, R36S Studio needs a special permission to access your SD card directly, even "
        "after you entered your administrator password: Full Disk Access.\n\n"
        "1. Open System Settings → Privacy & Security.\n"
        "2. Scroll down to \"Full Disk Access\".\n"
        "3. Use the button below to go there directly, or go there yourself.\n"
        "4. Click \"+\", choose R36S Studio in the list, then turn on the switch next to its name.\n"
        "5. Come back to R36S Studio and start the operation again.\n\n"
        "This permission is only needed once per version of the application. If access is blocked "
        "again after an update, just come back to this screen and start over: rebuilding the "
        "application changes its signature, which cancels the previous permission."
    ),
    "help_back": "Back",
    "help_open_settings": "Open settings",
    "fda_welcome_title": "Welcome to R36S Studio",
    "fda_welcome_body": (
        "Before you start, your Mac blocks two things by default: opening an application that does "
        "not come from a developer recognized by Apple, and letting that application access an SD "
        "card directly.\n\n"
        "1. If you haven't done it yet: close this window, right-click R36S Studio in the Finder, "
        "choose \"Open\", then confirm — only once.\n"
        "2. Open System Settings → Privacy & Security → Full Disk Access (use the button below to "
        "go there directly).\n"
        "3. Click \"+\", choose R36S Studio in the list, then turn on the switch next to its name.\n"
        "4. Come back here and click \"I'm done\".\n\n"
        "This permission is only needed once per version of the application: if it is blocked again "
        "after an update, you will need to repeat these steps."
    ),
    "fda_welcome_open_settings": "Open settings",
    "fda_welcome_done": "I'm done",
    "fda_welcome_still_not_detected": (
        "Permission not detected yet. Check that R36S Studio is turned on in the Full Disk Access "
        "list, then try again."
    ),
    "about_version": "R36S Studio v{version} ({suffix})",
    "about_build": "build of {timestamp}",
    "about_dev": "development version",
    "error_partition_not_found": (
        "Could not find the console's files on this card. Did you prepare this card with R36S Studio?"
    ),
    "error_partition_not_mounted": "The card could not be opened properly. Unplug it, plug it back in, then try again.",
    "error_easyroms_ntfs_macos": (
        "Your Mac cannot copy games to this card because of a system limitation. Use a Windows or "
        "Linux PC for this step."
    ),
    "error_mountpoint_not_writable": "Could not write to your card. Check that it is not write-protected, then try again.",
    "error_device_not_allowed": "This card is no longer accessible. Unplug it, then plug it back in.",
    "error_source_not_found": "The chosen folder cannot be found.",
    "error_verify_failed": "The check after writing failed. Try again with a new card.",
    "error_cancelled": "The operation was cancelled before it finished.",
    "error_eject_failed": (
        "Could not eject the card. Close the files open on it, then try again, or remove it manually."
    ),
    "error_elevation_refused": "The Windows permission was refused. Try again and accept the prompt.",
    "error_reset_card_failed": (
        "Could not reset this card. Unplug it, plug it back in, close the windows showing it, then try again."
    ),
    "error_macos_tcc_blocked": (
        "Your Mac blocks access to the SD card until R36S Studio has the Full Disk Access permission. "
        "Open Help to turn it on."
    ),
    "error_macos_tcc_protected_folder": (
        "Your Mac blocks access to this file because it is in a protected folder (Downloads, Desktop "
        "or Documents). Move it somewhere else, then try again."
    ),
    "error_seven_zip_archive": (
        "This file is a 7-Zip archive. Extract it first — you will get an .img file you can flash directly."
    ),
    "error_unsupported_image_format": "This file is not a usable image. Accepted formats: .img, .img.gz, .img.xz.",
    "error_rocknix_asset_not_found": (
        "Could not find the ROCKNIX version for your console online. Try again later, or choose a "
        "file you already downloaded."
    ),
    "error_rocknix_checksum_mismatch": "The downloaded file is corrupted or incomplete. Try again.",
    "error_rocknix_download_failed": "The download failed. Check your internet connection, then try again.",
    "error_games_partition_not_found": (
        "Could not recognize where the games are (EASYROMS or STORAGE) on this card — the system "
        "backup without the games does not know where to stop."
    ),
    "error_insufficient_disk_space": (
        "Your computer does not have enough free space to create this backup. Free up some space, or "
        "choose another drive, then try again."
    ),
    "error_destination_too_small": (
        "This card is too small for the backup to install. Use a new card at least the same size."
    ),
    "error_doublons_io_error": "A read or write error occurred. Check that the folder is still accessible.",
    "error_destination_not_writable": "Could not write to the destination folder -- check that it is not read-only.",
    "error_path_outside_root": "A file to move is no longer in the scanned folder.",
    "error_destination_inside_root": (
        "This folder is inside the scanned folder -- the next scan would find it again. Choose a "
        "folder outside it, or keep the default destination (_doublons)."
    ),
    "error_destination_filesystem_root": "This folder is the root of a whole drive -- choose a subfolder.",
    "error_copy_verification_failed": (
        "The copy to the other drive could not be verified -- the original file was not touched."
    ),
    "error_move_file_failed": "Moving a file failed. See the log for details.",
    "error_partial_move_completed": "The move finished with at least one file skipped after a failure.",
    "error_fat_file_size_limit": (
        "The destination drive is formatted as FAT, which cannot hold files larger than 4 GB -- at "
        "least one selected file is larger than that."
    ),
    "error_output_exists": (
        "A file with the same name already exists in this location. Choose another name or another folder."
    ),
    "error_image_not_found": "The chosen image file cannot be found. It may have been moved or deleted.",
    "error_io_error": "A read or write error occurred. Check that the card is still plugged in.",
    "error_volume_in_use": (
        "The card seems to be used by another program (File Explorer, Windows Search, an "
        "antivirus…). Close the windows showing it, then try again."
    ),
    "error_unsupported_os": "This operation is not supported on this system.",
    "error_confirmation_refused": "Writing cancelled: the confirmation was not received.",
    "error_invalid_args": "Invalid command.",
    "error_generic": "An error occurred.",
    "system_backup_estimating": "Calculating the estimated size…",
    "system_backup_estimate_result": "Estimated size: about {size} (without the games).",
    "file_system_backup_size": "Estimated size: about {size} (without the games).",
    "android_screen_title": "Android console",
    "android_back_button": "← Back to home",
    "android_refresh_button": "Refresh",
    "android_consent_title": "adb is not installed",
    "android_consent_body": (
        "This tool needs adb (Google's official \"platform-tools\") to read the information of your "
        "Android console over USB. Nothing is installed yet — this page only offers it to you."
    ),
    "android_consent_url_label": "Address: {url}",
    "android_consent_size_label": "Download size: about {size}",
    "android_consent_size_unknown": "Download size: unknown",
    "android_consent_download_button": "Download adb",
    "android_downloading_status": "Downloading adb…",
    "android_download_cancel_button": "Cancel",
    "android_download_error": "The adb download failed.",
    "android_detecting_status": "Detecting…",
    "android_state_no_device_title": "No console detected",
    "android_state_no_device_help": (
        "1. On your console, open Settings → About phone.\n"
        "2. Tap the build number (or an equivalent line) 7 times in a row to turn on developer mode.\n"
        "3. Open Settings → Developer options, then turn on USB debugging.\n"
        "4. Connect the console to this computer with a USB cable.\n"
        "The exact menu varies from one console to another — look for \"USB debugging\" in the "
        "settings if these steps don't match exactly."
    ),
    "android_state_unauthorized_title": "Console detected, but not authorized",
    "android_state_unauthorized_help": (
        "Your console is plugged in, but it has not accepted this computer yet. A message should "
        "appear on its screen: accept the USB debugging request, then click Refresh."
    ),
    "android_state_multiple_title": "Several consoles detected",
    "android_state_multiple_help": (
        "Several Android consoles are plugged in at the same time. Unplug all the consoles except "
        "the one you want to prepare, then click Refresh."
    ),
    "android_state_adb_error_title": "adb did not respond",
    "android_state_adb_error_help": (
        "adb did not respond correctly. Check that the console is plugged in, then click Refresh. If "
        "the problem persists, unplug and plug the USB cable back in."
    ),
    "android_device_card_title": "Console detected",
    "android_device_label_manufacturer": "Manufacturer",
    "android_device_label_model": "Model",
    "android_device_label_product_name": "Product name",
    "android_device_label_android_version": "Android version",
    "android_device_label_abi": "Architecture",
    "android_value_not_found": "Not found",
    "android_catalog_search_button": "Look up this console in the catalog",
    "android_catalog_searching": "Searching…",
    "android_catalog_not_found": "This console was not found in the catalog.",
    "android_catalog_found_title": "Entry found",
    "android_emulators_title": "Recommended emulators",
    "android_emulators_generic_notice": (
        "Generic list: this list could not be adapted to your console (architecture or Android "
        "version not read)."
    ),
    "android_emulator_licence_a_verifier": "License to be checked",
    "android_emulator_prix_a_verifier": "Price to be checked",
    "android_emulator_status_actif": "Active project",
    "android_emulator_status_abandonne": "Abandoned project",
    "android_emulator_status_a_verifier": "Status to be checked",
    "android_emulator_official_link": "Open the official page",
    "android_emulator_source_link": "See the source",
    "android_emulator_variant_label": "Variant:",
    "android_category_all": "All ({count})",
    "android_check_all_button": "Check all",
    "android_uncheck_all_button": "Uncheck all",
    "android_checked_counter": "{checked}/{total} checked",
    "android_raw_output_title": "Technical output (adb)",
    "tri_title": "Sort my games",
    "tri_hint": (
        "Choose a folder where your games are mixed together. Each game will be moved to its "
        "console's folder, with the name your console's system expects. Nothing is deleted, and "
        "you will see everything before confirming."
    ),
    "tri_firmware_label": "Your console's system:",
    "tri_firmware_treefrogui": "TreeFrogUI (SF3000, SF2000…)",
    "tri_firmware_verified": "Folder names checked on a real card.",
    "tri_firmware_unverified": (
        "Folder names taken from this system's official configuration, not yet checked on a real card."
    ),
    "tri_choose_folder_button": "Choose the folder…",
    "tri_scan_title": "Scanning your games",
    "tri_scan_count": "{count} file(s) examined",
    "tri_cancel_button": "Cancel",
    "tri_back_button": "Back",
    "tri_preview_title": "Here is what will happen",
    "tri_preview_summary": (
        "{sorted} game(s) sorted into {folders} folder(s), {unidentified} file(s) set aside in \"_non_identifies\"."
    ),
    "tri_preview_nothing": "Nothing to sort in this folder: everything is already in place.",
    "tri_preview_risk": (
        "Check the folder names below: if a name does not match what your console expects, it will "
        "not show any game from that folder."
    ),
    "tri_group_folder": "{folder} — {count} game(s), {size}",
    "tri_group_unidentified": "_non_identifies — {count} item(s) set aside",
    "tri_group_left_in_place": "Left where they are — {count} game(s)",
    "tri_group_kept_folders": "Folders already sorted, not touched — {count}",
    "tri_case_warning": (
        "The folder \"{found}\" already exists, but your console's system expects \"{expected}\" "
        "(upper and lower case matter). Rename it first: this console's games are left where they are."
    ),
    "tri_item_with_reason": "{name} — {reason}",
    "tri_sort_button": "Sort",
    "tri_confirm_title": "Confirm the sorting",
    "tri_confirm_message": (
        "{count} file(s) will be moved within \"{root}\". Nothing will be deleted, and you can put "
        "everything back with \"Undo the sorting\"."
    ),
    "tri_confirm_button": "Confirm",
    "tri_move_title": "Sorting",
    "tri_move_count": "{done} / {total} file(s)",
    "tri_result_title": "Sorting complete",
    "tri_result_cancelled_title": "Sorting interrupted",
    "tri_result_moved": "{count} file(s) moved.",
    "tri_result_failures": "{count} file(s) could not be moved (see the list below).",
    "tri_result_aborted": (
        "The sorting stopped after several failures in a row. The card or drive may have been removed."
    ),
    "tri_result_skipped_existing": (
        "{count} item(s) left where they are: a file with the same name is already in \"_non_identifies\"."
    ),
    "tri_result_missing": "{count} file(s) had disappeared since the preview.",
    "tri_undo_button": "Undo the sorting",
    "tri_undo_previous_button": "Undo the previous sorting of this folder",
    "tri_undo_done": "{count} file(s) put back where they were.",
    "tri_undo_conflicts": (
        "{count} file(s) could not be put back (a file already takes their original place, or they "
        "were moved since)."
    ),
    "tri_done_button": "Done",
    "tri_error_root_filesystem_root": "Choose a more specific folder than the root of a drive.",
    "tri_error_root_user_folder": "Choose a more specific folder than your whole personal folder.",
    "tri_error_root_system_folder": "This folder already has the name of a console: choose the folder that contains it.",
    "tri_error_too_many_files": "This folder contains too many files. Choose a more specific folder.",
    "tri_error_not_writable": "Could not write to this folder (read-only or access denied).",
    "tri_error_io_error": "Could not read or write in this folder.",
    "tri_reason_header_mismatch": "the contents do not match its extension",
    "tri_reason_bin_unknown": ".bin file whose console could not be determined",
    "tri_reason_disc_image": "disc image: console not determined automatically",
    "tri_reason_disc_image_missing_files": "incomplete disc image (missing file: {detail})",
    "tri_reason_archive_7z": ".7z archive: contents not examined",
    "tri_reason_zip_multiple": "archive containing several files (arcade game?)",
    "tri_reason_zip_empty": "archive without a game",
    "tri_reason_zip_unreadable": "unreadable or protected archive",
    "tri_reason_unknown_extension": "file type not recognized",
    "tri_reason_unreadable": "unreadable file",
    "tri_reason_system_not_supported": "{system} console: not supported by this system",
    "tri_reason_extension_not_accepted": "this system does not show {detail} files for this console",
    "tri_reason_folder_case_conflict": "the expected folder \"{detail}\" already exists, spelled differently",
    "language_selector_label": "Langue / Language",
    "language_restart_title": "Langue / Language",
    "language_restart_message": "The new language will apply the next time you start R36S Studio.",
    "unit_bytes": "B",
    "unit_kb": "KB",
    "unit_mb": "MB",
    "unit_gb": "GB",
    "unit_tb": "TB",
    "device_list_entry": "{display} — {size_go:.1f} GB — {bus}",
    "datetime_label": "{month} {day}, {year} at {hour:02d}:{minute:02d}",
    "month_01": "January",
    "month_02": "February",
    "month_03": "March",
    "month_04": "April",
    "month_05": "May",
    "month_06": "June",
    "month_07": "July",
    "month_08": "August",
    "month_09": "September",
    "month_10": "October",
    "month_11": "November",
    "month_12": "December",
    "success_backup": "{display} has been backed up to {path}.",
    "success_backup_system": "The system of {display} has been backed up to {path}.",
    "success_extract_boot": "The original screen and settings have been copied to your computer.",
    "success_extract_easyroms": "Your games and saves have been copied to your computer.",
    "success_inject_boot": "{display} has its original screen back.",
    "success_copy_games": "The games have been copied to {display}.",
    "success_reset_card": "{display} has been reset.",
    "success_ready": "{display} is ready.",
    "eject_multiple_cards": "Several cards detected -- unplug the ones that are not involved, then try again.",
    "eject_card_not_found": "Card not found -- check that it is still plugged in, then try again.",
    "cancelled_after_bytes": "Operation cancelled after {done} bytes",
    "cancelled_or_elevation_failed": "The operation was cancelled or the permission request failed.",
    "reveal_finder": "Show in Finder",
    "reveal_explorer": "Show in File Explorer",
    "reveal_file_manager": "Show in the file manager",
    "macos_tcc_hint": (
        "macOS blocks access to the SD card even with administrator rights: R36S Studio does not "
        "have (or no longer has) the Full Disk Access permission. Go to System Settings → Privacy & "
        "Security → Full Disk Access, add R36S Studio (or remove it and add it again if it is already "
        "there: the app's signature changes with every rebuild, which cancels the previous "
        "permission), then start the operation again. See the Help screen from the home screen for "
        "the detailed steps."
    ),
    "macos_protected_folder_hint": (
        "macOS blocks access to this file because it is in a protected folder (Downloads, Desktop or "
        "Documents): the elevated worker does not have the same permission as Terminal or the Finder "
        "for these locations, even if one of them has it. Move the file somewhere else — for example "
        "directly in your home folder — then try again."
    ),
}
