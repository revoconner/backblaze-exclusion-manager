# Backblaze Exclusion Manager
### Now easier to use
A small Python program to fine tune exclusion list for Backblaze personal backup. 
Exclude files or folders from being backed up and eating up your precious bandwidth.

<img width="450" height="auto" alt="image" src="https://github.com/user-attachments/assets/e895591b-3a70-4c57-8821-23d5e24a989e" />

## How to use (v2.0)
1. Select the drive you want to backup in the backblaze control panel. ![image](https://github.com/user-attachments/assets/b4bfd9fd-c96c-4e09-8f51-a9c8a86b6eb1)
2. Uncheck anything you don't want uploaded from each of the drive being backed up.
3. Anything checked will be backed up, anything not checked will be excluded. It's as simple as that.
4. It's a good idea to backup the original file by clicking the backup button. (The backup will copy the same file and save it with extension .xml_DDMMYYhhmmss where the suffix is the date and time.)
5. Always a good idea to remove all extensions from the default exclusion list in backblaze control panel. 

## Why is it needed
Backblaze personal backup only allows user to select drives to backup, and for any folder or file they add to exclusion, those exclusion list, it affects all selected drive. No selected path is tied to one drive letter. So if you exclude say C:\Windows it will exclude D:\Windows as well, which is not very convenient.
</br>
</br>
Backblaze does allow you to manually edit exclusion list using an xml file (Article here https://www.backblaze.com/computer-backup/docs/configure-custom-exclusions-using-xml-windows), but individually doing that is cumbersome. This program lets you do that by just choosing the files or folders you want excluded.


## Disclaimers
1. Backblaze logo is a trademark of the Backblaze, Inc.
2. Not affliated with Backblaze or Backblaze, Inc.
3. Run as administrator to avoid problems. (Optional)
4. Always a good idea to create backups of the default xml list before making any edits.
5. Since I do not have a mac system, no compiled version for mac is supported. Please use the python script to compile an app if you want.
6. For windows and Mac only. (Windows have an exe)

## Changelog
- V 1.0 Initial Commit
- V 1.1 Added Mac support, code cleanup (thanks metadaddy for the merge request)
- V 2.0 Changed to a more user friendly option where you get what you see, instead of mentally calculating and selecting everything you want excluded. 
