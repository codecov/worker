As everyone will have their personal vscode preferences,
and might want to override settings inside of the workspace,
here is how you can make changes locally, without git prompting you to commit
your changes to these settings files:

```
git update-index --assume-unchanged .vscode/settings.json
```

This way, git will ignore your local changes, and you are free to change these
files as you see fit.
