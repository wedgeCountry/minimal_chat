Usage manage cli examples:

 ```bash
   # Create invitation link
   python -m scripts.manage_cli invite -u "https://trixie.wedgecountry.de:6565/" -e user@example.com 

   # Create reset link (user must be registered)
   python -m scripts.manage_cli reset -u "https://trixie.wedgecountry.de:6565/" invite -e user@example.com 
 ```