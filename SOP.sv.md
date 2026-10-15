# SOP: att genomföra en session i Studie 1

*Svensk översättning av `SOP.md`. Om de två skiljer sig åt gäller den engelska.*

Standardrutinen för att genomföra en session med studiens programvara. Den är till för
försöksledaren i labbet, på papper eller på en andra skärm.

- Du förväntas känna till studieprotokollet (Bilaga 1). Det här dokumentet beskriver hur
  programvaran genomför det.
- Ord i **fetstil** är exakt vad skärmen visar: en knapp, ett fält eller ett meddelande. Texterna
  är de svenska. Startfönstret visas på svenska bara om det öppnas med
  `python run_session.py --language sv` (avsnitt 2.1), och sessionsfönstret när
  **Försöksledarens språk** är **Svenska**. Texterna på deltagarens skärm visas på det
  **Deltagarens språk** som valts för sessionen.
- **[TBC: …]** markerar ett steg som programvaran och Bilaga 1 ännu inte avgör. Fråga S före
  sessionen om något av dem berör dig.

En session tar ungefär tre timmar. Programvaran leder dig genom varje fas i tur och ordning och
hoppar aldrig över någon. **Den tar tid på faserna; du startar var och en.** Ingenting startar
förrän du trycker på en knapp.

---

## 0. Två regler som alltid gäller

**Skattningarna visas inte för dig.** Deltagaren skattar på sin egen skärm, bakom skynket. Din
skärm säger bara **Väntar på deltagarens svar.** och sedan **Svar mottaget.** Den säger aldrig vad
skattningen var. (Det enda undantaget är förhandsgranskningen av anpassningen, avsnitt 12.3.)

**Du är blindad för vilken sorts beröring det är.** Tre sorters beröring används i studien, en per
besök. Programvaran väljer vilken utifrån allokeringsfilen och registrerar den i data. Den visas
aldrig på din skärm, och den här SOP:n beskriver dem inte. Om du märker att beröringen känns eller
låter annorlunda än vid ett annat besök är det väntat och inget fel. Nämn det inte för deltagaren,
och försök inte lista ut vilken det är.

Vad du får säga till deltagaren om studien styrs av Bilaga 1 §3.3 och
forskningspersonsinformationen (Bilaga 3a). Använd informationens egna ord: studien undersöker
**hur människor upplever beröring och smärta** – vad som känns behagligt, vad som känns obehagligt,
och hur de två slagen av upplevelser hänger ihop. Deltagaren får veta att **plagget ger tre olika
slags beröring, en vid varje besök**, och inget mer. **Säg eller antyd aldrig att
beröringen förväntas minska smärtan, och nämn aldrig forskningsprogrammets namn.** Beskriv inte ett
besöks beröring som annorlunda än ett annats.

För att hålla blindningen:

- Öppna inte datafilerna under en session, eller någon gång innan S säger till. De registrerar
  vilken sorts beröring som gavs.
- Öppna inte mönstermappen och titta inte på filnamnen i den.
- Öppna inte **Skapa ett mönster** i startfönstret. Det är S:s verktyg för att skapa mönstren, och
  det visar deras namn och form. Om du hittar det öppet, stäng det utan att läsa.

---

## 1. Före dagen

### 1.1 Labbdatorn

1. Kontrollera att programvaran är installerad och uppdaterad (`docs/SETUP.md`, "Keeping it up to
   date"; på svenska `docs/SETUP.sv.md`, "Hålla programvaran uppdaterad"). Hämta alla
   uppdateringar som S har meddelat.
2. Kontrollera att båda skärmarna är anslutna: deltagarens skärm (HP) bakom skynket, och laptopens
   egen skärm för dig. Deltagarens fönster öppnas i helskärm på HP-skärmen.
   **Sitt så att du inte kan se förbi skynket till deltagarens skärm.** Deltagaren skattar på en
   skärm du inte kan se, så att inget deltagaren rapporterar når dig under sessionen.
3. Kontrollera att deltagarens hörlurar (Bose) och laptopens högtalare är anslutna. Dina larm
   spelas i laptopens högtalare, och deltagarens ljud i hörlurarna.
4. Öppna startfönstret (avsnitt 2.1) och välj **Förhandsgranska schemat**. Läs tidslinjen och
   eventuella varningar. Ingenting startas.

### 1.2 Utrustning

Ha allt detta inom räckhåll innan deltagaren kommer.

| Utrustning | Används till |
|---|---|
| Monofilamentsatsen, alla filament som listas i `config/filaments.yaml` | Smärtmått, kartläggning |
| Den mjuka getpenseln | Penselmått |
| Termoden (TCS II med T09-proben), påslagen och programmerad separat. Programvaran skickar inget till den | Sensitisering, återuppvärmning |
| 0,075 % capsaicinkräm, med det som behövs för att applicera och ta bort den | Capsaicin |
| En hudpenna och en linjal i mm | Markering av det sensitiserade området, kartläggning |
| Öronproppar | Ljudinställning, vid behov |
| Hörlurar till deltagaren | Från ljudinställningen och framåt |
| Deltagarens fjärrkontroll (Logitech R400) | Hela sessionen |
| Det aktuerande plagget och dess försörjning | Från förberedelserna och framåt |
| Smärtteckningen på papper | Sessionens början (Bilaga 1 §3.3) |

**[TBC: materialet för att applicera och ta bort capsaicin, och var den fysiska stoppknappen och
snabbtömningen sitter på plagget som används.]**

### 1.3 Vägning av filamenten: startfönstret, sedan Instrument och miljö

Gör detta när filamentsatsen är ny, och igen när S ber om det. Tills det är gjort använder
programvaran tillverkarens krafter, och raden med öppna punkter visar punkt 1.

1. Väg varje filament på precisionsvågen.
2. Öppna startfönstret och välj **Instrument och miljö**.
3. Under **Filamentkrafter**, skriv in vad vågen visar, i gram, i filamentets fält **Vägt (g)**.
   Kraften i mN som kommer att sparas visas bredvid, under **Kraft (mN)**. Filamenten identifieras
   med **Märkning (g)**, som står tryckt på dem.
4. Skriv in **Vägningsdatum (ÅÅÅÅ-MM-DD):**.
5. Tryck på **Spara krafterna**. Meddelandet **Sparade … uppmätta krafter i filaments.yaml.**
   bekräftar det.

Vad meddelandena betyder:

| Meddelande | Vad du gör |
|---|---|
| **Skriv in vägningsdatumet innan uppmätta krafter sparas.** | Skriv in datumet och tryck på **Spara krafterna** igen. |
| **… är inte ett datum på formen ÅÅÅÅ-MM-DD.** | Skriv om datumet, till exempel `2026-09-24`. |
| **Filament … g: … är inte en vikt i gram över noll.** | Rätta det filamentets värde. |
| **Inga uppmätta krafter har skrivits in.** | Inget nytt skrevs in i kolumnen **Vägt (g)**. Ett värde som lämnats som det visades när fönstret öppnades sparas inte igen, så väg om och skriv in den nya avläsningen. |

Att spara ändrar `config/filaments.yaml` på labbdatorn.
**[TBC: vem som committar den ändrade filaments.yaml, så att vägningen bevaras.]**

---

## 2. Att starta en session

### 2.1 Öppna startfönstret

1. Öppna PowerShell i repository-mappen och aktivera studiens miljö, som i `docs/SETUP.md` steg 8
   (`docs/SETUP.sv.md` steg 8).
2. Kör `python run_session.py --language sv`. Utan `--language sv` öppnas startfönstret på
   engelska.
3. Startfönstret öppnas med fem val: **Kör en session**, **Instrument och miljö**, **Skapa ett
   mönster**, **Förhandsgranska schemat** och **Kontrollera utrustningen**. **Skapa ett mönster**
   är endast för S: öppna det inte (se "För att hålla blindningen" ovan). Att starta en session
   stänger det om det lämnats öppet.

### 2.1a Kontrollera utrustningen, innan deltagaren kommer

Välj **Kontrollera utrustningen**. Ingenting registreras. Gör varje del:

1. **Fjärrkontroll.** Tryck på var och en av de fyra knapparna några gånger. Varje tryck ska öka
   räknaren under just den knappens symbol, och inget annat. ▶ skickar två tangenter i tur och
   ordning, och båda räknas på ▶. Om ett tryck räknas under fel symbol, avbryt och säg till S.
2. **Skärmar.** Tryck på **Visa en etikett på deltagarens skärm**. Orden **Deltagarens skärm** ska
   fylla skärmen bakom skynket. Om de i stället visas på din skärm, klicka bort dem och säg till S.
3. **Ljud.** Båda enheterna ska visa vad som hittades. **hittades inte** betyder att hörlurarna
   eller högtalarna inte är de som studien är inställd för: kontrollera kabeln eller
   Bluetooth-anslutningen och säg till S. Sätt på dig hörlurarna själv, tryck på **Starta bruset**
   och höj nivån tills du hör det. Tryck på **Spela signalen**: du ska höra ett pip över bruset.
   Tryck på **Spela larmet**: det ska komma från laptopens högtalare, inte från hörlurarna.
4. **Plagg.** Välj dagens plagg, tryck på **Anslut**, slå sedan på och av varje kanal och se på
   ärmen. Tryck på **Koppla från**.
5. Tryck på **Stäng**. Det stänger av allt och släpper plagget och hörlurarna.

Vid en pilot eller ett test, använd deltagarkoderna **901** till **910**, aldrig en riktig
deltagares kod.

### 2.2 Innan du öppnar sessionsdialogen

Gör detta med deltagaren, som Bilaga 1 §3.3 anger. Det registreras utanför den här programvaran.

1. Bekräfta att deltagaren inte har ont i dag och inte har tagit smärtstillande. Om något av detta
   inte stämmer bokas sessionen om.
2. Registrera de sessionsuppgifter som studien samlar in i REDCap (nikotinbruk, menstruationscykel,
   i förekommande fall). Vid första besöket, mät längd och vikt.
3. Låt deltagaren fylla i smärtteckningen på papper.

När REDCap-formuläret för sessionen är ifyllt bockar du i det i dialogen Kör en session (avsnitt
2.4). Programvaran registrerar bara det, inte vad formuläret innehåller.

### 2.3 Rumstemperatur och luftfuktighet (valfritt)

1. I **Instrument och miljö**, fyll i **Temperatur (°C):** och **Luftfuktighet (% RF):** under
   **Rumsmiljö (valfritt)**.
2. Tryck på **Använd för nästa session**. Startfönstret visar **Rummet … °C, … % RF, lämnas till
   nästa session.**

Värdena sparas bara tills startfönstret stängs, och en session kan köras utan dem.

### 2.4 Dialogen Kör en session

1. Välj **Kör en session**.
2. Fyll i alla fält. Inget är ifyllt åt dig utom datamappen.

   | Fält | Vad du fyller i |
   |---|---|
   | **Deltagarkod** | Koden från allokeringsfilen, till exempel `07`. Aldrig ett namn. |
   | **Sessionsnummer** | Detta besök: 1, 2 eller 3. |
   | **Försöksledarens initialer** | Dina. Använd samma vid varje besök. |
   | **Deltagarens språk** | Språket deltagaren läser: Svenska eller English. |
   | **Försöksledarens språk** | Språket du vill ha din skärm på. |
   | **Plagg** | Plagget du kontrollerade i avsnitt 2.1a. Aldrig **Simulerat plagg (ingen hårdvara)** med en deltagare. |
   | **Datamapp** | Låt den vara som den är (`data`) om inte S säger något annat. |
   | **Mönstermapp** | Mappen som S har angett för studien. Det finns ingen standardmapp. **Bläddra…** öppnas där mönstermapparna finns. **[TBC: sökvägen till mönstermappen för riktiga sessioner (öppen punkt 5).]** |
   | **REDCap-formuläret för besöket är ifyllt** | Bocka i när deltagarens REDCap-formulär för detta besök är ifyllt (avsnitt 2.2). Det registreras i båda fallen, och det hindrar inte en session. |

3. Tryck på **Kontrollera**. Programvaran kontrollerar sessionen innan något skrivs, och listar vad
   den hittade under knapparna.
4. Läs resultatet (avsnitt 2.5).
5. Om inget vägras blir **Starta sessionen** tillgänglig. Tryck på den.

Om du ändrar något fält efter **Kontrollera** blir **Starta sessionen** grå igen. Tryck på
**Kontrollera** igen.

### 2.5 Vad Kontrollera kan säga

**Vägranden, i rött, under Sessionen kan inte starta:**

| Meddelande | Vad du gör |
|---|---|
| **Obligatoriskt: …** | Fyll i de fält som nämns och tryck på **Kontrollera** igen. |
| **Deltagarkoden … finns inte i allokeringsfilen. Kontrollera koden.** | Koden är felskriven, eller så finns inte det sessionsnumret för deltagaren. Kontrollera båda mot deltagarens uppgifter. |
| **Session … för denna deltagare är redan genomförd. Den körs inte igen.** | Sessionsnumret är fel, eller så har besöket redan ägt rum. Kontrollera deltagarens uppgifter. Försök inte kringgå det. |
| **En annan session körs redan från den här datamappen (…). Stäng den först.** | En annan kopia av programvaran är öppen. Hitta den och stäng den. Om ingen är öppen, se avsnitt 15. |

**Varningar, i gult, under Varningar. Sessionen kan starta, och var och en registreras:**

| Meddelande | Vad det betyder och vad du gör |
|---|---|
| **Dessa initialer skiljer sig från tidigare sessioner för denna deltagare. …** | Bilaga 1 §3.3 önskar samma försöksledare vid varje besök. Om du skrev fel initialer, rätta dem. Om en annan försöksledare genomför detta besök, fortsätt. Avvikelsen registreras. |
| **Inga data hittades för session … för denna deltagare. …** | Föregående sessions filer finns inte i den här datamappen. Kontrollera sessionsnumret. Om det stämmer (till exempel om session 1 kördes på en annan dator), fortsätt. Den första kalibreringen börjar då från det konfigurerade filamentet. |
| **Session … för denna deltagare har ingen godkänd skattning före sensitisering. …** | Föregående session slutförde inte sin första kalibrering. Fortsätt. Den första kalibreringen börjar från det konfigurerade filamentet. |
| **Session … för denna deltagare har startats tidigare och avbrutits. En ny session registreras vid sidan av den.** | Ett tidigare försök med detta besök avbröts. Fortsätt bara om detta är ett nytt försök som S har godkänt. |

### 2.6 Erbjudandet att återuppta efter en krasch

Om programvaran stannade oväntat under denna deltagares session frågar **Starta sessionen**
först:

> En oavslutad session hittades för denna deltagare. Genomfört: …. Sensitiseringen började för …
> sedan. Återuppta den med den ursprungliga tidsplanen?

- **Återuppta sessionen** fortsätter sessionen som kraschade. **Välj detta efter en krasch.**
  Avsnitt 12.5 beskriver vad det gör.
- **Starta en ny session** börjar om från förberedelserna. Den kraschade sessionens filer sparas.
  Välj det bara om S godkänner det. När capsaicin väl har applicerats kan en ny start inte
  genomföras som protokollet avser.
- Att stänga frågan startar ingenting.

### 2.7 Att starta från kommandoraden (för S, eller när S ber om det)

```
python run_session.py --participant 07 --session 1 --experimenter SM --patterns <mönstermapp>
```

Samma kontroller körs. Vägranden och varningar skrivs ut, och ett vägrande stoppar körningen. Om en
kraschad session hittas stannar den och ber dig lägga till `--resume` eller `--new`. Använd aldrig
`--clock-speed` för en riktig session: den snabbar upp varje intervall och registreras som en
utvecklingskörning.

---

## 3. Sessionsskärmen

Ditt fönster läses uppifrån och ned:

1. **Banderoller**, om några (avsnitt 13).
2. **Vem och var**: **Deltagare …**, **Session …**, **Målarm: …** och **Försöksledare …**.
3. **Fasen**, nedräkningen till nästa schemalagda händelse, och **Förfluten tid …**.
4. **En avbrottsrad**, när sessionen är pausad eller stoppad.
5. **Vad du ska göra nu**, med stor text. Statusraden under säger om ett svar väntas eller har
   kommit, och eventuella varningar.
6. **Zondiagrammet**, med zonen och platsen för den aktuella stimuleringen, och **Plagget** med
   anslutningsstatus och knappen **Koppla från plagget** / **Anslut plagget**.
7. **Knapparna** (avsnitt 11), sedan fälten för anteckning, utbyte och kartläggning.

**Nästa steg** är startknappen för allt, inte bara block. Tryck på den när instruktionen säger att
du ska trycka på Nästa steg.

**Fjärrkontrollen fungerar alltid, oavsett vilket fönster du senast klickade i.** Dess tryck går
till deltagarens skärm även när ditt eget fönster är aktivt. Undantaget är när du skriver i ett
textfält (en anteckning, ett utbyte eller ett avstånd): då hamnar deltagarens tryck i det fältet i
stället. Skriv klart och tryck på Enter innan deltagaren behöver svara.

---

## 4. Förberedelse

Fasen visar **Förberedelse**. Inget mäts ännu.

### 4.1 Sätt på plagget

1. Placera deltagaren med målarmen (**Målarm: …**) på armstödet, bakom skynket.
2. Skärmen visar **Sätt på plagget och kontrollera att alla fem kanaler sitter rätt.** Deltagarens
   skärm visar **Sessionen börjar snart.**
3. Sätt på plagget. Kontrollera att alla fem kanaler sitter rätt.
4. Ge deltagaren fjärrkontrollen och visa knapparna: de två stora knapparna flyttar markören åt
   vänster och höger, den blå play-knappen (▶) bekräftar, och det gula "!" är stoppet.
5. Sätt hörlurarna på deltagaren.
6. Tryck på **Nästa steg**.

**[TBC: när och hur den fysiska stoppknappen och snabbtömningen visas för deltagaren (Bilaga 1
§3.10). Programvaran övar bara mjukvarustoppet.]**

### 4.2 Välkomstskärmen

1. Deltagarens skärm visar välkomsttexten. Din skärm visar **Väntar på deltagarens svar.**
2. Deltagaren läser den och trycker på play. Sessionen går vidare av sig själv.

### 4.3 Övning med stoppknappen

Deltagaren trycker en gång, på riktigt, på mjukvarustoppet medan plagget är igång. Övningen kommer
före ljudinställningen, så att deltagaren känner till stoppet innan något annat begärs. Bruset har
inte startat än, så deltagaren kan höra plagget. Det tar ungefär en och en halv minut.

1. Skärmen visar:

   > Övning med stoppknappen: deltagaren trycker nu på stoppknappen. När stoppskärmen visas, tryck
   > på Återuppta. Tryck på Nästa steg bara om deltagaren inte kan trycka.

2. Deltagarens skärm ber deltagaren att trycka på stoppknappen. Det är fjärrkontrollens knapp för
   svart skärm.
3. När deltagaren trycker stannar plagget. Din skärm visar den röda raden **NÖDSTOPP. Plagget är på
   noll. Tryck på Återuppta när deltagaren är redo.** och instruktionen **Stoppet registrerades.
   Tryck på Återuppta för att fortsätta inför deltagaren.**
4. Tryck på **Återuppta**. Plagget startar igen, efter varningssignalen, och deltagaren ser att
   sessionen har fortsatt.
5. Deltagaren läser nästa skärm och trycker på play.
6. **Om deltagaren inte kan trycka**, tryck på **Nästa steg**. Övningen avslutas och registreras
   som inte tryckt.

**[TBC: öppen punkt L11. Tills övningstrycket är bestämt startas plagget utan tryck, så att
deltagaren ser stoppet och återupptagandet utan att känna beröringen stanna. Öppen punkt L12:
stoppknappen ritas på deltagarens skärm som en röd cirkel, en platshållare tills symbolen som står
tryckt på fjärrkontrollens knapp för svart skärm är bekräftad.]**

### 4.4 Ljudinställning: maskeringskontrollen

Deltagaren ställer själv in sin nivå på det vita bruset mot ljudet från plagget. Det tar några
minuter.

1. Skärmen visar **Ljudinställning: deltagaren ställer in brusnivån mot plagget.**
2. Deltagaren går igenom det på sin egen skärm: höjer bruset tills det hörs tydligt, plagget
   startar, och deltagaren höjer bruset tills det döljer plagget och trycker på play. Deltagarens
   skärm säger åt deltagaren att säga till dig om plagget fortfarande hörs.
3. Medan plagget är igång säger din skärm:

   > Ljudinställning: plagget är igång och deltagaren höjer bruset för att dölja det. Om deltagaren
   > säger att hen fortfarande hör plagget, tryck på Nästa steg. Bruset stängs av så att du kan
   > erbjuda öronproppar.

4. **Om deltagaren säger att plagget fortfarande hörs**, tryck på **Nästa steg**.
   1. Bruset och plagget stannar. Deltagarens skärm säger att sessionen är pausad, och statusen
      säger **Deltagaren hör fortfarande plagget. Erbjud öronproppar under hörlurarna. …**
   2. Erbjud öronpropparna. Sätt dem under hörlurarna.
   3. Instruktionen säger **Sätt öronpropparna under hörlurarna och tryck sedan på Nästa steg.**
      Tryck på **Nästa steg**.
   4. Kontrollen börjar om från början.
5. **Om deltagaren säger det igen med öronproppar**, tryck på **Nästa steg** igen. Statusen säger
   **Fortfarande hörbart med öronproppar. Sessionen fortsätter och registreras som inte helt
   maskerad.** Sessionen fortsätter och data registrerar det. Skriv en anteckning om deltagaren
   säger något om det.
6. Bruset förblir på deltagarens nivå härifrån, utom under kartläggningen och bytet av
   öronproppar.

---

## 5. Beröringskalibrering

Fasen visar **Beröringskalibrering**. Deltagaren ställer in och skattar beröringen från plagget på
sin egen skärm. Du följer med, och svarar bara när programvaran ber dig.

**[TBC: hur lång tid det tar (öppen punkt 8).]**

1. Instruktionen namnger varje steg medan det pågår:
   - **Beröringskalibrering, steg 1: deltagaren ställer in beröringen på mittkanalen.**
   - **Beröringskalibrering, steg 2: deltagaren skattar en serie beröringar. 3/12 besvarade.**
     Räknaren ökar när deltagaren svarar. Bara med det simulerade plagget eller prototypärmen
     visas en knapp **Hoppa över kalibreringen** efter några skattningar: den avslutar
     kalibreringen i förtid vid en pilot eller ett test, och data registrerar den som överhoppad
     och inte giltig för analys. Den visas aldrig med studieplagget.
   - **Beröringskalibrering, steg 3: deltagaren matchar kanal … mot mittkanalen.**
   - **Beröringskalibrering, steg 4: deltagaren jämför kanal … med mittkanalen.**
   - **Beröringskalibrering, steg 5: deltagaren ställer in den behagligaste nivån.**
   - **Beröringskalibrering: deltagaren får frågan om rörelsen känns jämn.**
   - **Beröringskalibrering, steg 6: deltagaren väljer en sorts beröring.**

   Steg 6 görs vid varje besök. Före steg 1, med plagget avstängt, övar deltagaren på
   intensitetsskalan och sedan på behaglighetsskalan (VAS-övning, avsnitt 6).

2. **När programvaran ber dig att bestämma:**

   | Instruktion | Vad du gör |
   |---|---|
   | **Skattningen i beröringskalibreringen klarade inte kvalitetskontrollen (…). Gör om proceduren, eller godkänn den för att fortsätta med skattningen flaggad.** | Tryck på **Gör om proceduren** för att upprepa steg 1 och 2, eller **Godkänn den här skattningen** för att fortsätta. En omkörning frågar efter en orsak, som sparas. **[TBC: när man ska göra om och när man ska godkänna.]** |
   | **Skattningen i beröringskalibreringen kan inte användas (…). Gör om proceduren, eller avbryt sessionen.** | Tryck på **Gör om proceduren**, eller **Avbryt sessionen** (avsnitt 11.3). **Godkänn den här skattningen** gör ingenting här. |
   | **Skattningen i beröringskalibreringen kan inte användas (…) och gränsen för antal omkörningar är nådd. …** | Tryck på **Godkänn den här skattningen** för att fortsätta med kalibreringen registrerad som inte giltig för analys, eller **Avbryt sessionen**. |
   | **Kanal … matchades åter vid 0 kPa. Balansera om för att göra om matchningen, eller gå vidare …** | Tryck på **Balansera om kanalerna** för att göra om matchningen, eller **Nästa steg** för att fortsätta med den kanalen registrerad som inte giltig för analys. |
   | **Deltagaren upplever rörelsen som ojämn längs armen. Balansera om kanalerna, eller gå vidare.** | Tryck på **Balansera om kanalerna** för att gå tillbaka till matchningen, eller **Nästa steg** för att fortsätta. |
   | **Skattningen i beröringskalibreringen är klar. Godkänn den, eller gör om proceduren.** | Bara med förhandsgranskningen av anpassningen påslagen (avsnitt 12.3). |

   Orden inom parentes anger vilken sorts fel det var: **platt**, **stiger inte med trycket**,
   **brusig**, **inget intervall mellan de två inställningarna**, **mål utanför vad plagget kan
   ge** eller **inget behaglighetsintervall kvar inom plaggets gränser**. De visar aldrig en
   skattning.

3. **Statusvarningar du kan se**, som inte kräver något av dig:
   - **Fler än tillåten andel av kontrollförsöken utan tryck rapporterades som kända (…).**
   - **Kanal … matchar fortfarande inte mittkanalen efter omjustering. Sessionen fortsätter och
     detta registreras.**

4. Efter kalibreringen stannar plagget, och skärmen visar **Utgångsläge: deltagaren skattar hur hen
   känner sig just nu.** Deltagaren besvarar två skattningar. Inget för dig att göra.

Bilaga 1 §3.7 nämner att pausa eller kalibrera om ifall komforten minskar senare i sessionen.
**[TBC: programvaran har ingen omkalibrering efter den här fasen. Paus (avsnitt 11.1) är det enda
alternativet, och sessionen skulle behöva avbrytas för att kalibrera om.]**

---

## 6. Före sensitisering

Fasen visar **Före sensitisering**. Mätningarna görs i den här ordningen:

1. Det långa protokollet, sekundära zonen (avsnitt 10). Zonen är inte sensitiserad än, så applicera
   bredvid området där sensitiseringen ska ges (Bilaga 1 §3.6.1).
2. Det korta protokollet, primära zonen, med 26 g-filamentet: fem appliceringar.
3. Penseln, sekundära zonen: fem drag.
4. Penseln, primära zonen: fem drag.

Varje mätning börjar med **Redo. Tryck på Nästa steg när deltagaren är redo.** Tryck på **Nästa
steg** när du och deltagaren är redo.

**VAS-övning** (Bilaga 1 §3.6.1, §3.9; SPEC.md §10.6). Programvaran ger den i varje session, en
gång per skala, innan skalan används första gången:

- **intensitetsskalan** och sedan **behaglighetsskalan**, i början av beröringskalibreringen
  (avsnitt 5), före steg 1, med plagget avstängt;
- **smärtskalan** här, efter att du startat det långa protokollet och före första filamentet.

Interventionen innehåller aldrig någon övning.

För varje skala:

1. Deltagaren ser skalan som den kommer att skattas, utan markör och utan något under den. Ingen
   knapp utom stoppknappen gör något på den än. Din skärm visar **Övning på skattningsskalan:
   förklara etiketterna längs linjen högt, och förklara att "…"**, med proportionalitetsmeningen
   för den skalan: *ett märke dubbelt så långt ut på linjen betyder att det gjorde dubbelt så ont*
   (eller att beröringen kändes dubbelt så *intensiv*, eller dubbelt så *behaglig*).
2. Läs varje gång högt upp varje etikett på deltagarens skärm och var den sitter på linjen (Bilaga 1
   §3.6.1, §3.9 kräver instruktioner om ändpunkterna), och säg sedan proportionalitetsmeningen.
   Tryck därefter på **Nästa steg**.
3. Deltagaren gör en **övningsskattning**: en rad under skalan ber deltagaren att flytta markören
   med de stora knapparna, åt båda hållen, och trycka på ▶. Om en knapp hålls nedtryckt går
   markören fortare ju längre den hålls. Din skärm säger att deltagaren övar; den visar aldrig var
   markören hamnade, och övningen sparas inte som en skattning.

Applicera inte något filament förrän din skärm visar instruktionen om applicering. Frågorna om
avslappning och vakenhet har ingen övning. Efter en krasch upprepar en återupptagen session inte
övningar som redan getts i samma session.

---

## 7. Värmesensitisering

1. Skärmen visar **Starta termoden på 50 °C. Programmet tar tid på fasen men styr inte enheten.**
2. Placera termoden på handryggen på målarmen.
3. Starta termodens program (Bilaga 1 §3.5: 50 °C i 2 min, med korta sänkningar till 32 °C var
   10,2 s).
4. **Tryck på Nästa steg i det ögonblick termoden startar.** Det trycket är sessionens tid noll:
   alla senare tider räknas från det, och **Förfluten tid** börjar räkna.
5. Markera det sensitiserade hudområdet med pennan (Bilaga 1 §3.5).

## 8. Capsaicin

1. Vid 2 minuter visar nedräkningen **Capsaicin ska starta nu.** Ett larm hörs på labbsidan cirka
   30 s innan och igen 60 s efter tidpunkten. Avsnitt 13.3 beskriver nedräkningen.
2. Skärmen visar **Applicera 0,075 % capsaicin.**
3. Applicera krämen på det sensitiserade området och gnid in den (Bilaga 1 §3.5). Tryck på **Nästa
   steg**. Fasen byts till **Capsaicin**.
4. Nedräkningen går till 32 minuter. Under tiden visar skärmen **Väntar på nästa schemalagda steg.
   Nedräkningen visar när det ska starta.**
5. Vid 32 minuter: **Ta bort capsaicinet och tryck sedan på Nästa steg för att börja mätningarna
   efter sensitiseringen.** Ta bort det och tryck sedan på **Nästa steg**.

---

## 9. Efter sensitisering

Fasen visar **Efter sensitisering**. Den här tidpunkten har kartläggningen. Ordningen är:

1. Det långa protokollet, sekundära zonen (avsnitt 10).
2. **Kartläggningen** (avsnitt 9.1).
3. Det korta protokollet, primära zonen, 26 g.
4. Penseln, sekundära zonen.
5. Penseln, primära zonen.

Interventionen ska starta vid 45 minuter. Om mätningarna blir klara tidigare väntar programvaran.

### 9.1 Kartläggningen

Det vita bruset är avstängt under hela kartläggningen, så att du och deltagaren kan prata. Det
slås på igen efteråt. Deltagarens skärm visar viloskärmen.

1. Före första banan visar skärmen texten som ska läsas högt:

   > Säg högt: "Jag kommer att röra vid dig med det här filamentet och flytta ett litet steg i
   > taget mot det markerade området. Säg till så snart känslan tydligt förändras – brännande,
   > ömmande eller vassare stick."

   Läs den för deltagaren.
2. Skärmen säger sedan **Bana … av 4. Tryck på Nästa steg för att starta taktsignalen, och igen för
   att stoppa den vid gränsen.** Banorna är **proximal**, **lateral**, **distal** och **medial**, i
   den ordningen.
3. Placera 26 g-filamentet (Bilaga 1 §3.6.2: 260 mN) på banan, långt utanför det sensitiserade
   området.
   **[TBC: hur långt ut varje bana börjar.]**
4. Tryck på **Nästa steg**. Skärmen visar **Kartlägg bana …. Flytta 5 mm inåt vid varje signal och
   stanna när deltagaren markerar.** Ett tick hörs en gång per sekund.
5. Vid varje tick, applicera filamentet 5 mm längre in.
6. När deltagaren säger att känslan tydligt har förändrats, tryck på **Nästa steg** igen för att
   stoppa tickandet.
7. Markera gränsen på huden med pennan.
8. Upprepa för nästa bana. Efter 40 tick (200 mm) stannar banan av sig själv.

### 9.2 Avstånden

**Mät varje gräns från mitten av den primära zonen och skriv in de fyra avstånden i mm när det
passar. Detta avbryter aldrig sessionen.**

1. Mät vart och ett av de fyra märkena från mitten av den primära zonen, i mm.
2. När du har en stund över, tryck på **Kartläggningsavstånd…**. Ett fönster öppnas bredvid din
   skärm. Sessionen fortsätter bakom det.
3. Välj tidpunkt, om fler än en listas. Den senaste är förvald.
4. Skriv in varje avstånd bredvid sin bana. Båda decimaltecknen fungerar (`23,5` eller `23.5`).
   Lämna ett fält tomt om du inte har mätt det än.
5. Tryck på **Registrera avstånd**. Du kan skriva in några nu och resten senare.
6. Tryck på **Stäng** när du är klar.

- **Ett orimligt värde.** Ett avstånd under 12,5 mm eller över 200 mm godtas inte direkt. Statusen
  säger **Bana …: … mm ligger utanför det rimliga intervallet. Skriv samma värde igen för att
  bekräfta det, eller skriv det rättade värdet.** Kontrollera mätningen. Tryck sedan på
  **Registrera avstånd** igen med samma värde för att bekräfta det, eller skriv in det rättade
  värdet.
- **En rättelse.** Om du skriver in ett annat värde för en bana som redan registrerats sparas det
  nya. Det gamla finns kvar i data.
- **I slutet av sessionen** efterfrågas eventuella saknade avstånd en gång (avsnitt 12.2).

---

## 10. Smärtmåtten: hur varje applicering går till

Gäller alla filament- och penselmått: före sensitisering, efter sensitisering, varje
filamentblock och efter intervention.

1. Tryck på **Nästa steg** vid **Redo. Tryck på Nästa steg när deltagaren är redo.**
2. För varje applicering:
   1. Skärmen anger stimuleringen: **Applicera filamentet … g (… mN) på plats …, … zonen.** eller
      **Borsta den … zonen på plats …: ett enda drag på cirka 2 cm.** Zondiagrammet ringar in
      zonen.
   2. Deltagaren ser en kort varningssignal. Applicera stimuleringen direkt efter den, på den plats
      som anges.
   3. Cirka 9 s senare visas deltagarens skattningsskala. Din statusrad säger **Väntar på
      deltagarens svar.**
   4. När deltagaren bekräftar säger den **Svar mottaget.**
   5. Programvaran väntar 13 till 17 s och anger sedan nästa applicering.
3. **Platsen byts vid varje applicering.** Använd alltid den plats som skärmen anger.
   **[TBC: var plats 1 till 8 ligger på huden. Zondiagrammet är en platshållare (öppen
   punkt 11).]**

Det långa protokollet pågår tills programvaran har sin skattning, upp till 25 appliceringar. Det
korta protokollet och penseln är fem appliceringar vardera.

### 10.1 Monofilamentteknik

Skärmen visar den under instruktionen när ett filament används:

> Applicera vinkelrätt från cirka 3 cm. Böj filamentet till ungefär tre fjärdedelar av dess
> utsträckta längd, håll kvar i cirka 1 s, ingen sidorörelse, lyft sedan långsamt. Håll
> appliceringsstället utom synhåll för deltagaren.

- Använd det filament som skärmen anger med dess grammärkning, som står tryckt på det.
- Håll appliceringsstället utom synhåll för deltagaren. Skynket sköter det.

### 10.2 Att använda ett annat filament: utbyte

Du får använda ett **lättare** filament än det som efterfrågas när du bedömer att det är befogat.
Programvaran anpassar då efter det filament du faktiskt applicerade.

1. Applicera det lättare filamentet.
2. Innan deltagaren bekräftar sin skattning, skriv dess grammärkning i **Filament använt i stället
   (g)**, exakt som den står tryckt (`2.0`, inte `2`).
3. Tryck på **Registrera filament**.

| Meddelande | Vad det betyder |
|---|---|
| **Inget filament märkt … g finns. Utbytet registrerades inte.** | Den märkningen finns inte i satslistan. Kontrollera den och skriv in den igen. |
| **Filamentet … g är inte lättare än det som efterfrågades. Det registreras som applicerat.** | Det registrerades. Om det var ett misstag, skriv en anteckning. |

### 10.3 Meddelanden från det långa protokollet

- **Kalibreringen tog slut på stegen (…). Yttersta filamentet används och försöket flaggas. Räkna
  med detta i en betydande andel av sessionerna.** Detta händer ibland och är väntat. Inget att
  göra.
- **Gränsen på … appliceringar är nådd. Bästa tillgängliga skattning används och flaggas.** Inget
  att göra.

En skattning högst upp på skalan gör automatiskt att programvaran slutar be om det filamentet
eller ett tyngre på den platsen, och på alla platser när flera platser har nått dit. Du får inget
besked om det. Du blir helt enkelt ombedd att använda lättare filament.

---

## 11. Knapparna

### 11.1 Pausa och Återuppta

- **Pausa** stoppar plagget direkt och visar deltagaren en pausskärm. Din skärm visar **Pausad.
  Plagget är på noll. Tryck på Återuppta för att fortsätta.**
- **Återuppta** startar plagget igen där det var, efter en varningssignal, och upprepar steget som
  avbröts.
- Ett försök som avbröts går förlorat och upprepas. Inget som redan samlats in ändras.
- Medan sessionen är pausad eller stoppad fungerar bara **Återuppta**, **Avbryt sessionen** och
  anteckningsfältet.

### 11.2 Kassera och upprepa senaste försöket

Använd den när ett filament eller penseldrag gavs felaktigt men deltagaren ändå skattade det.

1. Tryck på **Kassera och upprepa senaste försöket** efter **Svar mottaget.** och innan nästa
   applicering anges. Det är pausen på 13 till 17 s efter en skattning.
2. Statusen säger **Senaste försöket kasserat. Det upprepas.** Det kasserade försöket finns kvar i
   data, flaggat.
3. Om gränsen för antal appliceringar är nådd säger den **Senaste försöket kasserat. Gränsen för
   antal appliceringar är nådd, så det upprepas inte.**

Knappen godtas bara i filament- och penselmått, och bara i den pausen. Vid alla andra tillfällen
ignoreras trycket och loggas, och skärmen ändras inte. Det finns ingen knapp för att hoppa över ett
försök.

### 11.3 Avbryt sessionen

1. Tryck på **Avbryt sessionen** (i rött).
2. Dialogen säger **Avbryta sessionen? All data som samlats in hittills sparas.**
3. Skriv orsaken i **Orsak till avbrott**. **Avbryt-knappen förblir grå tills en orsak har
   skrivits in.**
4. Tryck på **Avbryt sessionen** för att avsluta sessionen, eller **Tillbaka** för att gå tillbaka.

Orsaken skrivs till data. En avbruten session kan inte återupptas.

### 11.4 Anteckningar

Skriv i **Tidsstämplad anteckning** och tryck på **Lägg till anteckning** (eller Enter).
Anteckningen sparas direkt, med tiden. Skriv en anteckning om allt ovanligt: vad deltagaren sa, ett
tappat filament, en störning i rummet.

### 11.5 Koppla från plagget och Anslut plagget

- **Koppla från plagget** stoppar plagget och kopplar från det. Sessionen fortsätter och inget går
  förlorat. **Plagget** visar då **Frånkopplad** i rött.
- **Anslut plagget** ansluter det igen. Om beröringen ska vara igång startar den igen efter
  varningssignalen. Under ett block startar den igen när blocket är slut.

**[TBC: när en försöksledare medvetet ska koppla från plagget.]**

---

## 12. Interventionen, efter interventionen och slutet

### 12.1 Interventionen

Fasen visar **Intervention**. Den varar i 120 minuter: tolv block, växelvis filament och
beröringsskattning, med återuppvärmningen i mitten.

1. Vid 45 minuter: **Interventionen börjar nu. Tryck på Nästa steg för att starta beröringen.**
   Tryck på **Nästa steg**.
2. Skärmen visar **Beröring: plagget startas.** i några sekunder. Det händer varje gång beröringen
   startas, vid varje besök. Sedan fortsätter sessionen.
3. Mellan blocken: **Väntar på nästa schemalagda steg. Nedräkningen visar när det ska starta.**
   Nedräkningen visar nästa block, till exempel **Nästa: block 3 (beröring) om 04:05**.
4. **När ett block ska starta** (avsnitt 13.3) visar skärmen **Redo. Tryck på Nästa steg när
   deltagaren är redo.** Tryck på **Nästa steg** en gång. Det trycket startar blocket.
   - **Ett filamentblock** är det korta protokollet i den sekundära zonen med det filament som
     programvaran valde efter sensitiseringen: fem appliceringar (avsnitt 10).
   - **Ett skattningsblock för beröring** visar **Skattningsblock för beröring: deltagaren skattar
     beröringen.** Deltagaren gör tolv skattningar av beröringen och av hur hen känner sig. Inget
     för dig att göra.
5. **Om du är sen**, starta blocket så snart du kan. Programvaran hoppar aldrig över eller kortar
   ett block. Den registrerar hur sent det var.
6. **Återuppvärmningen**, vid 105 minuter (60 minuter in i interventionen):
   1. Nedräkningen visar **Återuppvärmning ska starta nu.** Plagget stängs av.
   2. Skärmen visar **Återuppvärm nu. Plagget har avaktiverats och återaktiveras efteråt.**
   3. Placera termoden och starta återuppvärmningsprogrammet (Bilaga 1 §3.5: 45 °C i 2 min).
      **Tryck på Nästa steg när värmen startar.**
   4. Programvaran tar tid på återuppvärmningsfönstret, startar sedan plagget igen (**Beröring:
      plagget startas.**) och fortsätter med nästa block.
7. Vid 165 minuter: **Interventionen är slut och plagget har stängts av.** Sessionen går direkt
   vidare till efter interventionen.

### 12.2 Efter interventionen och sessionens slut

1. Fasen visar **Efter intervention**. Mätningarna är desamma som efter sensitiseringen, med
   kartläggningen (avsnitt 9 och 10).
2. **Om kartläggningsavstånd fortfarande saknas** säger skärmen **Kartläggningsavstånd saknas
   fortfarande. Skriv in dem nu, eller avsluta sessionen med dem flaggade som saknade.**
   - Skriv in dem med **Kartläggningsavstånd…** och tryck sedan på **Nästa steg**.
   - Eller tryck på **Nästa steg** för att avsluta med de saknade flaggade.

   Du får frågan bara en gång.
3. Deltagarens avslutningsskärm visas, och båda fönstren stängs. Sessionen är klar.
4. Ta av plagget och hörlurarna.

### 12.3 Förhandsgranskning av anpassningen (endast vid pilot)

När S har slagit på den visas den gula banderollen **FÖRHANDSGRANSKNING AV ANPASSNINGEN ÄR PÅ. …**
under hela sessionen. I slutet av varje långt protokoll och av beröringskalibreringen visar ett
fönster anpassningen med deltagarens skattningar, och du väljer **Godkänn den här skattningen**
eller **Gör om proceduren**. En omkörning frågar **Varför gör du om proceduren? Registreras
tillsammans med den kasserade skattningen, som sparas.** Efter gränsen: **Gränsen för antal
omkörningar av den här proceduren är nådd. Den här skattningen används.**

Slå aldrig på den själv. Den visar dig skattningar, som deltagaren har fått veta att du inte ser.

### 12.4 Tiderna i korthet

Tiderna räknas från trycket när termoden startar (sessionens tid noll). De kommer från
`config/schedule.yaml`, och **Förhandsgranska schemat** visar de aktuella.

| Tid | Steg |
|---|---|
| Före 0 | Förberedelse, beröringskalibrering, före sensitisering |
| 0 | Värmesensitisering, 2 min |
| 2 min | Capsaicin appliceras |
| 32 min | Capsaicin tas bort, efter sensitisering börjar |
| 45 min | Interventionen börjar |
| 55, 63, 71, 79, 87, 95 min | Block 1 till 6 |
| 105 min | Återuppvärmning |
| 117, 125, 133, 141, 149, 157 min | Block 7 till 12 |
| 165 min | Interventionen slutar, efter intervention |

Varje block beräknas ta 4 minuter. Det är en gissning tills piloten har mätt det (öppen punkt 4).

### 12.5 Efter en krasch: vad återupptagandet gör

Om programvaran stannar oväntat (en krasch, ett strömavbrott):

1. Säg till deltagaren att det blir en kort teknisk paus. Kontrollera att plagget inte är
   uppblåst.
   **[TBC: vad man gör med plagget om programvaran kraschade medan det var uppblåst.]**
2. Starta startfönstret igen och fyll i **Kör en session** precis som förut.
3. Tryck på **Kontrollera**, sedan **Starta sessionen**, och välj **Återuppta sessionen**.

Återupptagandet:

- fortsätter från det första steget som inte slutförts. Steget som pågick vid kraschen görs om, och
  dess tidigare rader sparas, markerade som ersatta;
- behåller den ursprungliga tiden noll, så att varje nedräkning fortsätter där den ska;
- läser in det som redan mätts (kalibreringarna, ljudnivån, de kartläggningsavstånd som redan
  skrivits in) och gör inte om det;
- under interventionen startar plagget igen efter varningssignalen;
- under återuppvärmningen ber aldrig om värmen en andra gång. Skärmen säger **Sessionen
  återupptogs under återuppvärmningen. Värmen startades före avbrottet och efterfrågas inte igen;
  återuppvärmningen räknas därifrån. Tryck på Nästa steg för att bekräfta. Om värmen i själva
  verket inte gavs, ge den nu och skriv en anteckning. Plagget förblir avstängt tills
  återuppvärmningen är klar.**

**Stäng inte sessionsfönstret för att starta om det.** Att stänga fönstret registrerar sessionen
som avbruten (i data med den engelska orsaken "the window was closed before the session
ended"), och en avbruten session kan inte
återupptas.

---

## 13. Nödlägen, banderoller och varningar

### 13.1 Deltagarens stopp

- **Den fysiska stoppknappen och snabbtömningen är den verkliga säkerhetsvägen.** De fungerar
  utan programvaran. Programvaran kan inte se dem.
- **Mjukvarustoppet** är fjärrkontrollens knapp för svart skärm (det gula "!", som skickar en
  punkt). Stoppet sätter plagget på noll direkt, visar deltagaren en stoppskärm och visar dig den
  röda raden **NÖDSTOPP. Plagget är på noll. Tryck på Återuppta när deltagaren är redo.**
- **Ditt tangentbord fungerar som fjärrkontrollen** utanför en textruta: punkt är nödstoppet, och
  F5 eller Esc är som när deltagaren trycker på ▶. Tryck inte på dem medan en session pågår.

När deltagaren trycker på något av dem:

1. Gå till deltagaren. Fråga om hen mår bra.
2. Om deltagaren vill avsluta sessionen, tryck på **Avbryt sessionen** och ange orsaken.
3. Om deltagaren är redo att fortsätta, tryck på **Återuppta**. Steget som avbröts upprepas.

Deltagaren har fått veta att ett tryck på stoppet inte stör experimentet. Återupptagandet håller
det löftet.

**[TBC: vad man trycker på i programvaran efter att deltagaren använt den fysiska stoppknappen,
som programvaran inte upptäcker. Att först pausa och skriva en anteckning verkar rimligt.]**

### 13.2 Banderoller högst upp på din skärm

| Banderoll | Vad den betyder | Vad du gör |
|---|---|---|
| Röd: **DELTAGARSKÄRMARNA INNEHÅLLER FORTFARANDE PLATSHÅLLARTEXT. Kör inte en riktig deltagare.** | En del av deltagartexten är inte slutgiltig. | **Kör inte en riktig deltagare.** Endast pilot med labbmedlemmar. |
| Gul: **DENNA SESSION SAMLAR INTE IN GILTIG BERÖRINGSKALIBRERINGSDATA. Den anslutna enheten kan inte ställa tryck per kanal: …. Tiderna är verkliga; trycken är det inte.** | Plagget som används kan inte ställa ett tryck per kanal, till exempel prototypen eller det simulerade plagget. | Går bra för att pilottesta tiderna. Inte en riktig datasession. |
| Gul: **FÖRHANDSGRANSKNING AV ANPASSNINGEN ÄR PÅ. Du ser deltagarens skattningar, …** | Avsnitt 12.3. | Endast vid pilot, om inte S säger annat. |

Banderollerna ligger kvar hela sessionen. Skärmen flyttar sig inte när en dyker upp.

### 13.3 Nedräkningen och larmen

| Visas | Betyder |
|---|---|
| Grått: **Nästa: … om mm:ss** | Nästa schemalagda steg och hur länge det är kvar till det. |
| Gult, fetstil: **Block … ska starta nu.** eller **… ska starta nu.** | Starta det när du är redo. |
| Rött, fetstil: **Block … är FÖRSENAT.** eller **… är FÖRSENAD.** | Starta det så snart du kan. |

Ett larm på labbsidan hörs 30 s innan varje steg ska starta, och igen 60 s efter om det inte har
startats. Deltagaren ska inte höra det (öppna punkter L3 och L10).

### 13.4 Raden med öppna punkter

Liten gul text under instruktionen: **Olösta konfigurationsplatshållare: …**, med punkternas
nummer. Håll muspekaren över den för att se vad var och en är. Samma lista skrivs ut när
programvaran startar.

Varje punkt är ett värde som bara S kan ta fram. Några av dem måste vara lösta före en riktig
deltagare.
**[TBC: om varje listad punkt hindrar en riktig session, eller bara de som är markerade
blocks_use i config/open_items.yaml.]**

### 13.5 Andra meddelanden

| Meddelande | Vad du gör |
|---|---|
| **Frånkopplad**, i rött, under **Plagget** | Kontrollera plaggets kabel och försörjning och tryck sedan på **Anslut plagget**. |
| **Fel: …** eller **Fel i plagget: … (detalj i data)** | Skriv en anteckning. Om det kvarstår, pausa och fråga S. |
| En dialog med rubriken **Fel** | Skriv ner meddelandet, tryck på **Stäng** och se avsnitt 15. |

---

## 14. Efter sessionen

### 14.1 Datafilerna

- De finns i den **datamapp** du valde, som standard mappen `data` i repositoryt.
- Varje session skriver en uppsättning CSV-filer vars namn består av datum och tid, sedan
  `P<kod>_S<session>_` och tabellen, till exempel `…_P07_S1_session.csv`, `…_P07_S1_log.csv` och
  `…_P07_S1_pinprick.csv`. En återupptagen session skriver en andra uppsättning, som hänvisar till
  den första.
- Varje rad sparas i samma ögonblick som den samlas in. Ingenting skrivs någonsin över.
- **Öppna, byt namn på, flytta eller radera dem inte** under sessionen eller innan de är
  uppladdade (avsnitt 14.2). De registrerar vilken sorts beröring som gavs.
- Låsfilen i datamappen tillhör programvaran. Låt den vara.

### 14.2 Uppladdning till studiens nätverkslagring

Studiens data finns på LiU:s nätverkslagring, i en *samarbetsmapp*:

```
\\fillager.liu.se\coop\t\tatp
```

LiU IT:s instruktioner för att ansluta till den:
<https://liudesk.liu.se/tas/public/ssp/content/detail/knowledgeitem?unid=c857f79e-6dfb-4f93-8f81-0b31a5efa9a2>

Den har tre mappar:

| Mapp | Vad som läggs där |
|---|---|
| `01_raw` | **Sessionens datafiler, exakt som programvaran skrev dem.** Det är hit du laddar upp. |
| `02_anonymised` | Inte din. Rör den inte. |
| `03_processed` | Inte din. Rör den inte. |

**Du laddar upp i slutet av varje session**, när programvaran har stängts.

1. Kopiera alla sessionens filer från datamappen till `01_raw`. Det är varje fil vars namn
   innehåller `P<kod>_S<session>_`, inklusive en återupptagen sessions andra uppsättning. Kopiera
   filerna; flytta dem inte.
2. Om Windows säger att en fil redan finns i `01_raw`, välj **Hoppa över** (Skip), aldrig
   **Ersätt** (Replace), och säg till S.
3. **Kontrollera uppladdningen.** Visa båda mapparna i vyn **Detaljer** (Details). För den här sessionens
   filer måste `01_raw` ha lika många filer som datamappen, med samma namn och samma storlek. Om
   något skiljer sig, kopiera den saknade eller avvikande filen igen, kontrollera igen, och säg
   till S om det fortfarande skiljer sig.
4. Byt inte namn på, redigera eller ordna inte om filerna, varken i datamappen eller i `01_raw`.
5. **Radera aldrig labbdatorns kopia.** Datamappen behåller varje session.

### 14.3 Vad som aldrig lämnar labbdatorn utom genom den uppladdningen

- Datafilerna. Aldrig via e-post, USB-minne, OneDrive eller någon annan molnsynkad mapp, och aldrig
  in i git. Mappen `data` är medvetet undantagen från git.
- Allt som kopplar en deltagarkod till ett namn. Det finns aldrig i programvaran eller dess filer.

### 14.4 Innan du går

1. Rengör och plocka undan filamenten, penseln och termoden.
2. Skriv ner det ovanliga som hände efter att sessionen stängdes, där S ber dig.
   **[TBC: var anteckningar efter sessionen ska skrivas.]**

---

## 15. Felsökning

| Problem | Vad du gör |
|---|---|
| Deltagaren trycker på knapparna och inget händer på deltagarens skärm. | Kontrollera om ett textfält på din skärm har markören i sig: medan du skriver hamnar fjärrkontrollens tryck i det fältet. Tryck på Enter eller klicka på en knapp. Annars når fjärrkontrollen deltagarens skärm oavsett vilket fönster som är aktivt. Om den fortfarande inte svarar, kontrollera fjärrkontrollens mottagare och batteri. **[TBC: dirigeringen är testad utan skärm, ännu inte på labbdatorn med den riktiga fjärrkontrollen.]** |
| Båda fönstren öppnades på labbskärmen. | Öppen punkt 9 är inte satt än. Säg till S. Kör inte en riktig deltagare. |
| **Starta sessionen** är grå. | Tryck på **Kontrollera**. Den blir grå igen varje gång ett fält ändras. |
| **En annan session körs redan från den här datamappen** men ingen annan kopia är öppen. | Leta efter ett dolt fönster i aktivitetsfältet. Om det inte finns något, starta om datorn och försök igen. |
| Startfönstret öppnades inte, eller ett långt felmeddelande skrevs ut i PowerShell. | Kopiera de sista raderna av meddelandet och skicka dem till S. Försök inte rätta konfigurationsfiler. |
| Programvaran kraschade under en session. | Avsnitt 12.5. |
| **Kassera och upprepa senaste försöket** gjorde ingenting. | Den fungerar bara under 13 till 17 s efter en filament- eller penselskattning. |
| **Godkänn den här skattningen** gjorde ingenting. | Den skattningen kan inte användas. Gör om, eller avbryt. |
| **Avbryt sessionen** i dialogen är grå. | Skriv en orsak. |
| Du hör inte larmen på labbsidan, eller deltagaren hör dem. | Öppna punkter L3 och L10. Säg till S. Håll ögonen på nedräkningen. |
| **Kartläggningsavstånd…** är grå. | Inget har kartlagts än i den här sessionen. |
