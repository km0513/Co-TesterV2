const qaQuotes = [
  
    {
        quote: "Quality is not a tool, it's a mindset.",
    },
    {
        quote: "The bitterness of poor quality remains long after the sweetness of low price is forgotten.",
    },
    {
        quote: "Quality is not an option, it's a requirement.",
    },
    {
        quote: "Quality is not about being perfect, it's about being better than yesterday.",
    },
    {
        quote: "Quality is not a cost, it's an investment.",
    },
    {
        quote: "Quality is not a department, it's everyone's responsibility.",
    }
];

function getDailyQuote() {
    const today = new Date();
    const dayOfYear = Math.floor((today - new Date(today.getFullYear(), 0, 0)) / (1000 * 60 * 60 * 24));
    const quoteIndex = dayOfYear % qaQuotes.length;
    return qaQuotes[quoteIndex];
}

function displayDailyQuote() {
    const quote = getDailyQuote();
    const quoteElement = document.getElementById('daily-quote');
    if (quoteElement) {
        quoteElement.innerHTML = `
            <div style="
                background: #f9f9f9;
                border-left: 5px solid #007bff;
                padding: 20px;
                margin-top: 30px;
                border-radius: 10px;
                box-shadow: 0 0 8px rgba(0,0,0,0.05);
                max-width: 800px;
                margin-left: auto;
                margin-right: auto;
            ">
                <p style="
                    font-size: 1.3em;
                    font-style: italic;
                    color: #cc0000;
                    margin-bottom: 10px;
                ">
                    "${quote.quote}"
                </p>
                <p style="
                    text-align: right;
                    font-weight: bold;
                    color: #444;
                    margin: 0;
                ">
                </p>
            </div>
        `;
    }
}

document.addEventListener('DOMContentLoaded', displayDailyQuote);
