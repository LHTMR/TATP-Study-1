# Setting up the TATP Study 1 software on a LiU Windows computer

This guide takes you from nothing to a computer that has the study software and everything it
needs installed. It covers setup only.

It is written for a LiU-managed Windows computer where you **do not have administrator
rights**. You don't need them: every step below works with a normal LiU account. If Windows ever
asks for an administrator password during these steps, the guide tells you what to do.

Allow about 45 minutes. Most of it is waiting for downloads.

**Already set up on this computer by someone else?** Some of the software (step 3) is shared
by everyone on the computer. Everything else is per person, so you still need to do the other
steps under your own login.

---

## 1. Create a GitHub account

GitHub is the website where the study software is stored. You need an account to download it
and, later, to report problems.

1. Go to <https://github.com/signup>.
2. Sign up with your **LiU email address**. This makes it easy for the study team to recognise
   you.
3. Choose a username. It is visible to others, so something recognisable (e.g. your name) is
   best.
4. GitHub will ask you to set up **two-factor authentication**. Do this: GitHub requires it,
   and it's easiest to set up now. An authenticator app on your phone works well.

## 2. Get access to the study repository

The software lives in a private repository called **LHTMR/TATP-Study-1**. You can't see it until
you have been added.

1. Send your **GitHub username** to PLACEHOLDER: name and email of the person who grants
   access, and ask to be added to `LHTMR/TATP-Study-1`.
2. You will get an email from GitHub with an invitation. Click **View invitation**, then
   **Accept**. The invitation expires after 7 days. If you miss it, ask for a new one.
3. Check that it worked: <https://github.com/LHTMR/TATP-Study-1> should now open instead of
   showing "404 — page not found". (Sign in first if it asks.)

## 3. Install the software from Company Portal

LiU installs software through **Company Portal** (called **Företagsportal** if Windows is in
Swedish). Open it from the Start menu.

Search for and install each of these four apps. The names below are what you'll see in Company
Portal:

| Search for | Install the one called | What it's for |
|---|---|---|
| `miniconda` | **Miniconda** (publisher: Conda) | Installs Python and the packages the software is built on |
| `git` | **Git** | Keeps track of software versions. The study software records which version collected each session's data, and it needs Git for that |
| `github` | **GitHub Desktop** (publisher: GitHub) | An easy way to download the software and keep it up to date |
| `make` | **Gnu Make**. Not CMake, which is a different tool | Short commands for common tasks, like `make preview` |

**Wait for each install to finish** before moving on. Company Portal shows **Installed** with a
blue tick when it's done. The download can finish several minutes before the install does.

If these are already marked **Installed**, someone else on this computer has installed them and
you can skip ahead.

## 4. Download the software with GitHub Desktop

1. Open **GitHub Desktop** and choose **Sign in to GitHub.com**. Sign in with the account from
   step 1 in the browser window that opens, then return to GitHub Desktop.
2. If it asks you to "Configure Git", enter your name and your LiU email address.
3. Choose **File → Clone repository**, open the **GitHub.com** tab and pick
   **LHTMR/TATP-Study-1**. (If it's not in the list, step 2 isn't done yet.)
4. Leave the **Local path** as suggested. It should end in
   `Documents\GitHub\TATP-Study-1`. Click **Clone**.

## 5. Change three Windows settings for your account

Two of the programs from step 3 don't tell Windows where they are, and Miniconda needs one
setting so that it downloads from the right place. You can change all three yourself. No
administrator rights are needed.

1. Open the Start menu and search for **Edit environment variables for your account**. (In
   Swedish: **Redigera miljövariabler för ditt konto**.) Open it.
2. In the **top** box ("User variables for …"), select **Path** and click **Edit…**.
3. Click **New** and paste:

   ```
   C:\Program Files\Miniconda\condabin
   ```

4. Click **New** again and paste:

   ```
   C:\Program Files (x86)\GnuWin32\bin
   ```

5. Click **OK** to close the Path window. You're back at the first window.
6. Still in the **top** box, click **New…** and fill in:

   | | |
   |---|---|
   | Variable name | `CONDA_DEFAULT_CHANNELS` |
   | Variable value | `https://conda.anaconda.org/conda-forge` |

   Click **OK**.

   *Why:* LiU's Miniconda is set to download from Anaconda's own servers, which requires
   accepting Anaconda's commercial terms of service. The study uses the free community source
   (conda-forge) instead, and this setting points Miniconda there. **If Miniconda ever asks you
   to accept Anaconda's terms of service, don't. Check this setting instead.**

7. Click **OK** to close the window.
8. **Close and reopen** any terminal windows, and VS Code if you use it, so that they see the
   new settings. If in doubt, sign out of Windows and back in.

## 6. Let PowerShell use conda

1. Open **PowerShell** from the Start menu. Use a new window, opened after step 5.
2. Type this and press Enter:

   ```
   conda init powershell
   ```

3. **Windows may ask for administrator approval. Click No (or Cancel).** The part you need has
   already been done by then. The rest tries to change files that belong to LiU's installation
   and aren't needed.
4. Close PowerShell.

## 7. Create the study's Python environment

The software needs a specific set of packages at specific versions, collected into an
"environment" called `tatp-study-1`. This step downloads about 350 MB.

1. Open a **new PowerShell** window.
2. Go to the folder you cloned in step 4:

   ```
   cd $HOME\Documents\GitHub\TATP-Study-1
   ```

3. Create the environment:

   ```
   conda env create -f environment.yml
   ```

   It prints a long list of packages and then takes several minutes. It is finished when you see
   `To activate this environment, use … conda activate tatp-study-1`.

## 8. Check that everything is in place

In the same PowerShell window, run each of these lines. Each one should print a result like the
example, and none should say "not recognized".

| Type | You should see something like |
|---|---|
| `git --version` | `git version 2.55.0.windows.5` |
| `make --version` | `GNU Make 3.81` |
| `conda env list` | a list that includes `tatp-study-1` |
| `conda activate tatp-study-1` | the start of the line changes from `(base)` to `(tatp-study-1)` |

If all four look right, setup is complete.

---

## If something goes wrong

**"conda" (or "make") is not recognized.** The Path entries from step 5 are missing or mistyped,
or the window was opened before you added them. Check the two lines in step 5 exactly, then
open a new PowerShell window.

**`CondaToSNonInteractiveError: Terms of Service have not been accepted`.** The
`CONDA_DEFAULT_CHANNELS` setting from step 5.6 is missing, or the window is older than the
setting. Add it, open a new window, and try again. Do not accept the terms.

**`conda activate` says conda isn't initialised, or PowerShell complains that scripts are
disabled.** Windows is blocking PowerShell from loading the conda setup. Run the following,
which only affects your own account and needs no administrator rights. Then open a new window:

```
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**`conda env create` says the environment already exists.** It was created before, perhaps by
an earlier attempt. Nothing more to do. Go to step 8.

**Clone fails, or LHTMR/TATP-Study-1 isn't listed in GitHub Desktop.** Your access isn't set up
yet. Check you accepted the invitation in step 2, and that GitHub Desktop is signed in to the
same account.

## Keeping it up to date

When you're told the software has been updated:

1. In GitHub Desktop, click **Fetch origin**, then **Pull origin**.
2. If you're told the environment changed too, open PowerShell in the repository folder (as in
   step 7) and run:

   ```
   conda env update -f environment.yml --prune
   ```
