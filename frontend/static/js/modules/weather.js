/**
 * Weather widget and motivational quotes for the dashboard header.
 * Uses Open-Meteo free API (no key required).
 */

const _WMO_ICONS = {
    0: ['Sereno', '\u2600\uFE0F'],
    1: ['Prevalentemente sereno', '\uD83C\uDF24\uFE0F'],
    2: ['Parzialmente nuvoloso', '\u26C5'],
    3: ['Coperto', '\u2601\uFE0F'],
    45: ['Nebbia', '\uD83C\uDF2B\uFE0F'],
    48: ['Nebbia gelata', '\uD83C\uDF2B\uFE0F'],
    51: ['Pioggerella leggera', '\uD83C\uDF26\uFE0F'],
    53: ['Pioggerella', '\uD83C\uDF26\uFE0F'],
    55: ['Pioggerella intensa', '\uD83C\uDF26\uFE0F'],
    61: ['Pioggia leggera', '\uD83C\uDF27\uFE0F'],
    63: ['Pioggia', '\uD83C\uDF27\uFE0F'],
    65: ['Pioggia forte', '\uD83C\uDF27\uFE0F'],
    71: ['Neve leggera', '\u2744\uFE0F'],
    73: ['Neve', '\uD83C\uDF28\uFE0F'],
    75: ['Neve forte', '\uD83C\uDF28\uFE0F'],
    80: ['Rovesci leggeri', '\uD83C\uDF26\uFE0F'],
    81: ['Rovesci', '\uD83C\uDF27\uFE0F'],
    82: ['Rovesci forti', '\uD83C\uDF27\uFE0F'],
    95: ['Temporale', '\u26C8\uFE0F'],
    96: ['Temporale con grandine', '\u26C8\uFE0F'],
    99: ['Temporale forte', '\u26C8\uFE0F']
};

const _QUOTES = [
    'Il successo non \u00e8 definitivo, il fallimento non \u00e8 fatale: \u00e8 il coraggio di continuare che conta. \u2014 Churchill',
    'Ogni grande impresa inizia con un primo passo. \u2014 Lao Tzu',
    'Non \u00e8 la pi\u00f9 forte delle specie che sopravvive, ma quella pi\u00f9 reattiva ai cambiamenti. \u2014 Darwin',
    'Il miglior modo per predire il futuro \u00e8 crearlo. \u2014 Peter Drucker',
    'Le opportunit\u00e0 non capitano, si creano. \u2014 Chris Grosser',
    'Credi di poterlo fare e sei gi\u00e0 a met\u00e0 strada. \u2014 Theodore Roosevelt',
    'L\u2019unico limite ai nostri risultati di domani sono i nostri dubbi di oggi. \u2014 F.D. Roosevelt',
    'Il lavoro duro batte il talento quando il talento non lavora duro. \u2014 Tim Notke',
    'Non arrenderti. Di solito \u00e8 l\u2019ultima chiave del mazzo quella che apre la porta. \u2014 Paulo Coelho',
    'Fai oggi quello che gli altri non vogliono fare, e domani farai quello che gli altri non possono fare. \u2014 Jerry Rice',
    'La perseveranza non \u00e8 una lunga corsa; \u00e8 tante brevi corse una dopo l\u2019altra. \u2014 Walter Elliot',
    'Il modo per iniziare \u00e8 smettere di parlare e iniziare a fare. \u2014 Walt Disney',
    'Non conta quante volte cadi, ma quante volte ti rialzi. \u2014 Proverbio',
    'La fortuna aiuta gli audaci. \u2014 Virgilio',
    'Ogni no ti avvicina a un s\u00ec. \u2014 Mark Cuban'
];

const _WEATHER_PHRASES = {
    0: 'Sole pieno: giornata perfetta per conquistare un nuovo lavoro!',
    1: 'Cielo quasi limpido: buon auspicio per le candidature!',
    2: 'Qualche nuvola, ma niente ferma la tua determinazione!',
    3: 'Cielo coperto fuori, ma dentro brilli di motivazione!',
    45: 'Nebbia fuori, ma la tua strada \u00e8 chiara!',
    48: 'Nebbia gelata: riscaldati con una candidatura vincente!',
    51: 'Pioggerella leggera: tempo ideale per stare al pc e candidarti!',
    53: 'Pioggerella: perfetto per concentrarsi sulle candidature!',
    55: 'Piove: niente distrazioni, focus sulle opportunit\u00e0!',
    61: 'Pioggia leggera: resta al caldo e manda quel CV!',
    63: 'Piove: giornata produttiva da casa!',
    65: 'Pioggia forte: nessuna scusa per non candidarsi!',
    71: 'Neve leggera: il mondo si ferma, tu vai avanti!',
    73: 'Neve: perfetto per lavorare al calduccio!',
    75: 'Nevicata: dedica la giornata a te stesso e al tuo futuro!',
    80: 'Rovesci: resta dentro e prepara il colloquio!',
    81: 'Pioggia a intermittenza: candidati tra una schiarita e l\u2019altra!',
    82: 'Rovesci forti: il tuo impegno \u00e8 pi\u00f9 forte della pioggia!',
    95: 'Temporale fuori: tempesta di candidature dentro!',
    96: 'Temporale con grandine: oggi si lavora da casa!',
    99: 'Temporale forte: energia pura, usala per il tuo futuro!'
};

function _loadWeather() {
    const el = document.getElementById('weather-widget');
    if (!el) return;

    const quoteIdx = Math.floor(Date.now() / 3600000) % _QUOTES.length;
    const quoteText = _QUOTES[quoteIdx];

    fetch('https://api.open-meteo.com/v1/forecast?latitude=45.13&longitude=8.45&current=temperature_2m,weather_code')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            const temp = Math.round(data.current.temperature_2m);
            const code = data.current.weather_code;
            const info = _WMO_ICONS[code] || ['N/D', '\uD83C\uDF21\uFE0F'];
            const phrase = _WEATHER_PHRASES[code] || quoteText;

            while (el.firstChild) el.removeChild(el.firstChild);

            const weatherLine = document.createElement('div');
            weatherLine.className = 'weather-line';
            weatherLine.textContent = info[1] + ' ' + temp + '\u00B0C ' + info[0];
            el.appendChild(weatherLine);

            const phraseLine = document.createElement('div');
            phraseLine.className = 'weather-quote';
            phraseLine.textContent = phrase;
            el.appendChild(phraseLine);
        })
        .catch(function() {
            while (el.firstChild) el.removeChild(el.firstChild);
            const quoteLine = document.createElement('div');
            quoteLine.className = 'weather-quote';
            quoteLine.textContent = quoteText;
            el.appendChild(quoteLine);
        });
}

_loadWeather();
