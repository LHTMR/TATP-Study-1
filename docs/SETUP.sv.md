# Installera programvaran för TATP Studie 1 på en Windows-dator vid LiU

*Svensk översättning av `docs/SETUP.md`. Om de två skiljer sig åt gäller den engelska.*

Den här guiden tar dig från ingenting till en dator där studiens programvara och allt den behöver
är installerat. Den handlar bara om installationen.

Den är skriven för en LiU-hanterad Windows-dator där du **inte har administratörsbehörighet**. Du
behöver ingen: varje steg nedan fungerar med ett vanligt LiU-konto. Om Windows någon gång ber om
ett administratörslösenord under stegen säger guiden vad du ska göra.

Räkna med cirka 45 minuter. Det mesta är väntan på nedladdningar.

**Har någon annan redan installerat på den här datorn?** En del av programvaran (steg 3) delas av
alla som använder datorn. Allt annat är personligt, så du behöver ändå göra de andra stegen
inloggad som dig själv.

---

## 1. Skapa ett GitHub-konto

GitHub är webbplatsen där studiens programvara finns. Du behöver ett konto för att ladda ner den
och, senare, för att rapportera problem.

1. Gå till <https://github.com/signup>.
2. Registrera dig med din **LiU-e-postadress**. Då blir det lätt för studiegruppen att känna igen
   dig.
3. Välj ett användarnamn. Det syns för andra, så något igenkännbart (t.ex. ditt namn) är bäst.
4. GitHub ber dig att ställa in **tvåfaktorsautentisering**. Gör det: GitHub kräver det, och det
   är enklast att göra nu. En autentiseringsapp i telefonen fungerar bra.

## 2. Få tillgång till studiens repository

Programvaran finns i ett privat repository som heter **LHTMR/TATP-Study-1**. Du kan inte se det
förrän du har lagts till.

1. Skicka ditt **GitHub-användarnamn** till PLACEHOLDER: namn och e-post till den som ger
   behörighet, och be att bli tillagd i `LHTMR/TATP-Study-1`.
2. Du får ett e-postmeddelande från GitHub med en inbjudan. Klicka på **View invitation** och
   sedan **Accept**. Inbjudan går ut efter 7 dagar. Om du missar den, be om en ny.
3. Kontrollera att det fungerade: <https://github.com/LHTMR/TATP-Study-1> ska nu öppnas i stället
   för att visa "404 — page not found". (Logga in först om den ber om det.)

## 3. Installera programmen från Företagsportal

LiU installerar program via **Företagsportal** (heter **Company Portal** om Windows är på
engelska). Öppna den från Start-menyn.

Sök efter och installera vart och ett av dessa fyra program. Namnen nedan är de du ser i
Företagsportal:

| Sök efter | Installera den som heter | Vad den behövs till |
|---|---|---|
| `miniconda` | **Miniconda** (utgivare: Conda) | Installerar Python och paketen som programvaran bygger på |
| `git` | **Git** | Håller reda på programversioner. Programvaran registrerar vilken version som samlade in varje sessions data, och behöver Git för det |
| `github` | **GitHub Desktop** (utgivare: GitHub) | Ett enkelt sätt att ladda ner programvaran och hålla den uppdaterad |
| `make` | **Gnu Make**. Inte CMake, som är ett annat verktyg | Korta kommandon för vanliga uppgifter, som `make preview` |

**Vänta tills varje installation är klar** innan du går vidare. Företagsportal visar
**Installerad** (Installed) med en blå bock när den är klar. Nedladdningen kan bli klar flera minuter innan
installationen är det.

Om programmen redan är markerade som **Installerad** har någon annan på datorn installerat dem,
och du kan hoppa vidare.

## 4. Ladda ner programvaran med GitHub Desktop

1. Öppna **GitHub Desktop** och välj **Sign in to GitHub.com**. Logga in med kontot från steg 1 i
   webbläsarfönstret som öppnas, och gå sedan tillbaka till GitHub Desktop.
2. Om den ber dig att "Configure Git", fyll i ditt namn och din LiU-e-postadress.
3. Välj **File → Clone repository**, öppna fliken **GitHub.com** och välj
   **LHTMR/TATP-Study-1**. (Om det inte finns i listan är steg 2 inte klart än.)
4. Låt **Local path** vara som föreslaget. Den ska sluta på
   `Documents\GitHub\TATP-Study-1`. Klicka på **Clone**.

## 5. Ändra tre Windows-inställningar för ditt konto

Två av programmen från steg 3 talar inte om för Windows var de finns, och Miniconda behöver en
inställning för att ladda ner från rätt ställe. Du kan ändra alla tre själv. Ingen
administratörsbehörighet behövs.

1. Öppna Start-menyn och sök efter **Redigera miljövariabler för ditt konto**. (På engelska:
   **Edit environment variables for your account**.) Öppna den.
   Windows-knapparnas engelska namn står inom parentes nedan.
2. I den **övre** rutan ("Användarvariabler för …", "User variables for …"), markera **Path** och
   klicka på **Redigera…** (Edit…).
3. Klicka på **Ny** (New) och klistra in:

   ```
   C:\Program Files\Miniconda\condabin
   ```

4. Klicka på **Ny** igen och klistra in:

   ```
   C:\Program Files (x86)\GnuWin32\bin
   ```

5. Klicka på **OK** för att stänga Path-fönstret. Du är tillbaka i det första fönstret.
6. Fortfarande i den **övre** rutan, klicka på **Ny…** (New…) och fyll i:

   | | |
   |---|---|
   | Variabelnamn (Variable name) | `CONDA_DEFAULT_CHANNELS` |
   | Variabelvärde (Variable value) | `https://conda.anaconda.org/conda-forge` |

   Klicka på **OK**.

   *Varför:* LiU:s Miniconda är inställd på att ladda ner från Anacondas egna servrar, vilket
   kräver att man godkänner Anacondas kommersiella användarvillkor. Studien använder i stället den
   fria community-källan (conda-forge), och den här inställningen pekar Miniconda dit. **Om
   Miniconda någon gång ber dig att godkänna Anacondas användarvillkor, gör inte det. Kontrollera
   den här inställningen i stället.**

7. Klicka på **OK** för att stänga fönstret.
8. **Stäng och öppna igen** alla terminalfönster, och VS Code om du använder det, så att de ser de
   nya inställningarna. Om du är osäker, logga ut från Windows och logga in igen.

## 6. Låt PowerShell använda conda

1. Öppna **PowerShell** från Start-menyn. Använd ett nytt fönster, öppnat efter steg 5.
2. Skriv detta och tryck på Enter:

   ```
   conda init powershell
   ```

3. **Windows kan be om administratörsgodkännande. Klicka på Nej (eller Avbryt).** Den del du
   behöver är redan gjord då. Resten försöker ändra filer som tillhör LiU:s installation och
   behövs inte.
4. Stäng PowerShell.

## 7. Skapa studiens Python-miljö

Programvaran behöver en viss uppsättning paket i vissa versioner, samlade i en "miljö" som heter
`tatp-study-1`. Det här steget laddar ner cirka 350 MB.

1. Öppna ett **nytt PowerShell**-fönster.
2. Gå till mappen du klonade i steg 4:

   ```
   cd $HOME\Documents\GitHub\TATP-Study-1
   ```

3. Skapa miljön:

   ```
   conda env create -f environment.yml
   ```

   Den skriver ut en lång lista med paket och tar sedan flera minuter. Den är klar när du ser
   `To activate this environment, use … conda activate tatp-study-1`.

## 8. Kontrollera att allt finns på plats

Kör var och en av de här raderna i samma PowerShell-fönster. Var och en ska skriva ut ett
resultat som liknar exemplet, och ingen ska säga "not recognized" (eller "känns inte igen").

| Skriv | Du ska se ungefär |
|---|---|
| `git --version` | `git version 2.55.0.windows.5` |
| `make --version` | `GNU Make 3.81` |
| `conda env list` | en lista som innehåller `tatp-study-1` |
| `conda activate tatp-study-1` | början av raden ändras från `(base)` till `(tatp-study-1)` |

Om alla fyra ser rätt ut är installationen klar.

---

## Om något går fel

**"conda" (eller "make") känns inte igen ("is not recognized").** Path-raderna från steg 5
saknas eller är felskrivna, eller så öppnades fönstret innan du lade till dem. Kontrollera de två
raderna i steg 5 noga och öppna sedan ett nytt PowerShell-fönster.

**`CondaToSNonInteractiveError: Terms of Service have not been accepted`.** Inställningen
`CONDA_DEFAULT_CHANNELS` från steg 5.6 saknas, eller så är fönstret äldre än inställningen. Lägg
till den, öppna ett nytt fönster och försök igen. Godkänn inte villkoren.

**`conda activate` säger att conda inte är initierat, eller PowerShell klagar på att skript är
inaktiverade.** Windows hindrar PowerShell från att läsa in condas inställningar. Kör följande,
som bara påverkar ditt eget konto och inte kräver administratörsbehörighet. Öppna sedan ett nytt
fönster:

```
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**`conda env create` säger att miljön redan finns.** Den skapades tidigare, kanske vid ett
tidigare försök. Inget mer att göra. Gå till steg 8.

**Kloningen misslyckas, eller LHTMR/TATP-Study-1 finns inte i listan i GitHub Desktop.** Din
behörighet är inte ordnad än. Kontrollera att du godkände inbjudan i steg 2, och att GitHub
Desktop är inloggat med samma konto.

## Hålla programvaran uppdaterad

När du får veta att programvaran har uppdaterats:

1. Klicka på **Fetch origin** och sedan **Pull origin** i GitHub Desktop.
2. Om du får veta att miljön också har ändrats, öppna PowerShell i repository-mappen (som i
   steg 7) och kör:

   ```
   conda env update -f environment.yml --prune
   ```

---

*Utvecklaranteckningarna i slutet av den engelska `docs/SETUP.md` är inte översatta. Inget ovan
behöver dem.*
