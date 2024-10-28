# Backblaze Exclusion Manager
A small windows program to fine tune exclusion list for backblaze personal backup. 
Exclude files or folders from being backed up and eating up your previous bandwidth.

![image](https://github.com/user-attachments/assets/d3cec3e3-be51-4862-93a7-1726df7b571b)

## How to use
1. Use the buttons to select file or a folder.
2. To remove something from the exclusion list, select it from the list and click the "Remove Selected" button. This will promp a dialog box asking you confirm your action. This is undoable.
3. You can backup the xml file that these entries is being written into. The backup will copy the same file and save it with extension .xml_DDMMYYhhmmss where the suffix is the date and time.
4. Always a good idea to remove all extensions from the default exclusion list like this in backblaze control panel. ![image](https://github.com/user-attachments/assets/b4bfd9fd-c96c-4e09-8f51-a9c8a86b6eb1)


 ## Understanding the list
 The list entries have several nuances
 1. Starts with: if an entry has this, then it's not tied to any drive letter.
 2. Path: Path to a folder or a file. If a drive letter is not included in this, then it's not tied to any drive letter.
 3. Ends with: same as path but just contains the final part of a path. So for example
 4. This will affect all folders in any drive letter that starts with /users/ and ends with /cookies/index.dat as long as its a file with a .dat extenstion so it will affect: DD/users/randomassname/cookies/index.dat as long as index.dat is a file and not a folder.![image](https://github.com/user-attachments/assets/2cf79d3b-5752-4559-b4d9-3ea3c740b1b2)
 5. When user adds a folder it appears like this, with the drive letter. Pretty self explanatory.![image](https://github.com/user-attachments/assets/1fb7e7c1-be06-4f92-af6d-5339e0836fce)
 6. When user adds a file it appears like this, with the drive letter but also with "ends with" as the file name, and extension of the file. ![image](https://github.com/user-attachments/assets/acfe46d0-89b4-4663-ad3c-36c69a238561)



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
5. Created for Windows and tested on Windows. I do not recommend using the python script to run this program on a mac, unless specifically modified to be used on mac.
