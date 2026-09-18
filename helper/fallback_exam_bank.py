"""Deterministic fallback question bank.
Used when DB or AI models need supplementary curriculum questions or offline generation,
so the app always generates age-appropriate, subject-specific questions for any grade and question count.
"""

KIDS_QUESTION_BANKS = {
    "computer science": [
        {
            "type": "mcq",
            "questionText": "Which part of a computer looks like a TV screen and displays our work? 🖥️",
            "options": ["A) Monitor", "B) Keyboard", "C) Mouse", "D) CPU"],
            "correctAnswer": "A",
            "explanation": "A Monitor is the visual display unit that shows pictures, text, and videos on the computer.",
            "topic": "Parts of a Computer",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which key is the longest key on the keyboard and is used to give spaces between words? ⌨️",
            "options": ["A) Enter Key", "B) Spacebar", "C) Shift Key", "D) Backspace"],
            "correctAnswer": "B",
            "explanation": "The Spacebar is the longest horizontal key on the keyboard used to insert space between words.",
            "topic": "Keyboard Skills",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which device is known as the 'Brain of the Computer'? 🧠",
            "options": ["A) Mouse", "B) Monitor", "C) CPU", "D) Printer"],
            "correctAnswer": "C",
            "explanation": "CPU (Central Processing Unit) performs all calculations and controls all parts of the computer.",
            "topic": "Computer Fundamentals",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What hand-held device has 2 buttons and a scroll wheel to point and click on items? 🖱️",
            "options": ["A) Mouse", "B) Microphone", "C) Speaker", "D) Scanner"],
            "correctAnswer": "A",
            "explanation": "A computer mouse is a pointing device used to click, double click, and drag items.",
            "topic": "Input Devices",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which key do we press to start typing on a new line? ↵",
            "options": ["A) Caps Lock", "B) Enter Key", "C) Escape Key", "D) Delete Key"],
            "correctAnswer": "B",
            "explanation": "The Enter key moves the cursor to the beginning of the next line.",
            "topic": "Keyboard Skills",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which output device is used to print our drawings and stories on paper? 🖨️",
            "options": ["A) Printer", "B) Webcam", "C) Keyboard", "D) Joystick"],
            "correctAnswer": "A",
            "explanation": "A printer produces a paper copy (hard copy) of documents stored in the computer.",
            "topic": "Output Devices",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What software program is used to draw and color digital pictures on the computer? 🎨",
            "options": ["A) MS Paint", "B) Calculator", "C) Notepad", "D) Media Player"],
            "correctAnswer": "A",
            "explanation": "MS Paint is a simple graphics painting program included with Microsoft Windows.",
            "topic": "Fun Tools & Paint",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which key turns on CAPITAL letters when you type words? 🔠",
            "options": ["A) Caps Lock", "B) Spacebar", "C) Backspace", "D) Arrow Key"],
            "correctAnswer": "A",
            "explanation": "Pressing the Caps Lock key allows all typed letters to appear in UPPERCASE.",
            "topic": "Keyboard Skills",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which device helps us listen to music and games from our computer? 🔊",
            "options": ["A) Speakers", "B) Scanner", "C) Keyboard", "D) Mouse"],
            "correctAnswer": "A",
            "explanation": "Speakers output audio sound signals so we can hear songs, voices, and game effects.",
            "topic": "Output Devices",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which tool in Paint allows you to fill a whole shape with your favorite color? 🪣",
            "options": ["A) Fill with Color (Bucket)", "B) Pencil Tool", "C) Eraser Tool", "D) Magnifier"],
            "correctAnswer": "A",
            "explanation": "The 'Fill with Color' bucket tool floods any closed boundary or shape with color.",
            "topic": "Fun Tools & Paint",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "A small blinking vertical line on the monitor that shows where you will type next is called: ✍️",
            "options": ["A) Cursor", "B) Icon", "C) Desktop", "D) Taskbar"],
            "correctAnswer": "A",
            "explanation": "The Cursor is the blinking mark that indicates your current typing position.",
            "topic": "Typing Basics",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which portable computer can easily sit on your lap and run on battery? 💻",
            "options": ["A) Laptop", "B) Supercomputer", "C) Mainframe", "D) Server Tower"],
            "correctAnswer": "A",
            "explanation": "A laptop is a compact, portable computer that you can carry and use anywhere.",
            "topic": "Types of Computers",
            "marks": 1,
        },
    ],
    "mathematics": [
        {
            "type": "mcq",
            "questionText": "What is the sum of 25 + 15? ➕",
            "options": ["A) 40", "B) 35", "C) 50", "D) 45"],
            "correctAnswer": "A",
            "explanation": "25 + 15 = 40.",
            "topic": "Addition",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "How many sides does a triangle have? 🔺",
            "options": ["A) 3", "B) 4", "C) 5", "D) 2"],
            "correctAnswer": "A",
            "explanation": "A triangle is a closed geometric shape with exactly 3 straight sides and 3 angles.",
            "topic": "Basic 2D Shapes",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is 7 multiplied by 4 (7 × 4)? ✖️",
            "options": ["A) 28", "B) 24", "C) 32", "D) 21"],
            "correctAnswer": "A",
            "explanation": "7 × 4 = 28.",
            "topic": "Multiplication Tables",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "If you have 50 rupees and buy a chocolate for 20 rupees, how much money is left? 🍫",
            "options": ["A) 30 Rupees", "B) 25 Rupees", "C) 35 Rupees", "D) 20 Rupees"],
            "correctAnswer": "A",
            "explanation": "50 - 20 = 30 rupees remaining.",
            "topic": "Money & Subtraction",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which of these numbers is an EVEN number? 🔢",
            "options": ["A) 18", "B) 15", "C) 21", "D) 9"],
            "correctAnswer": "A",
            "explanation": "Even numbers are cleanly divisible by 2 and end in 0, 2, 4, 6, or 8. 18 is even.",
            "topic": "Odd & Even Numbers",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the place value of 6 in the number 462? 🎯",
            "options": ["A) 60 (Tens)", "B) 600 (Hundreds)", "C) 6 (Ones)", "D) 6000 (Thousands)"],
            "correctAnswer": "A",
            "explanation": "In 462, 4 is hundreds (400), 6 is tens (60), and 2 is ones (2).",
            "topic": "Place Value",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "How many minutes are there in ONE full hour? ⏱️",
            "options": ["A) 60 minutes", "B) 100 minutes", "C) 30 minutes", "D) 24 minutes"],
            "correctAnswer": "A",
            "explanation": "There are 60 minutes in 1 hour.",
            "topic": "Time Measurement",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is 80 minus 35 (80 - 35)? ➖",
            "options": ["A) 45", "B) 55", "C) 40", "D) 50"],
            "correctAnswer": "A",
            "explanation": "80 - 35 = 45.",
            "topic": "Subtraction",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "A square has how many equal sides? 🔲",
            "options": ["A) 4 equal sides", "B) 3 sides", "C) 5 sides", "D) 0 sides"],
            "correctAnswer": "A",
            "explanation": "A square has 4 straight sides of equal length and 4 right angles.",
            "topic": "Basic 2D Shapes",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is 9 × 5? 🌟",
            "options": ["A) 45", "B) 40", "C) 54", "D) 36"],
            "correctAnswer": "A",
            "explanation": "9 × 5 = 45.",
            "topic": "Multiplication Tables",
            "marks": 1,
        },
    ],
    "science": [
        {
            "type": "mcq",
            "questionText": "What part of a plant absorbs water and minerals from deep under the soil? 🌱",
            "options": ["A) Roots", "B) Flower", "C) Leaves", "D) Fruit"],
            "correctAnswer": "A",
            "explanation": "Roots hold the plant firmly in the soil and absorb water and essential nutrients.",
            "topic": "Plants Around Us",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which animal is famous as the 'Ship of the Desert'? 🐪",
            "options": ["A) Camel", "B) Elephant", "C) Lion", "D) Horse"],
            "correctAnswer": "A",
            "explanation": "Camels can survive for weeks without water and walk effortlessly across sandy dunes.",
            "topic": "Animal Habitats",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Ice is which physical state of water? 🧊",
            "options": ["A) Solid", "B) Liquid", "C) Gas", "D) Plasma"],
            "correctAnswer": "A",
            "explanation": "Water freezes into ice at 0°C, turning into a solid state.",
            "topic": "States of Matter",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which human sense organ helps us hear songs and sounds? 👂",
            "options": ["A) Ears", "B) Eyes", "C) Nose", "D) Tongue"],
            "correctAnswer": "A",
            "explanation": "Our ears receive sound vibrations allowing us to hear.",
            "topic": "Our Sense Organs",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What gives green color to the leaves of plants? 🍃",
            "options": ["A) Chlorophyll", "B) Sunlight", "C) Carbon", "D) Sugar"],
            "correctAnswer": "A",
            "explanation": "Chlorophyll is the green pigment in leaves that captures sunlight for photosynthesis.",
            "topic": "Plant Life",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "The Earth gets heat and light energy naturally from the: ☀️",
            "options": ["A) Sun", "B) Moon", "C) Stars", "D) Wind"],
            "correctAnswer": "A",
            "explanation": "The Sun is our closest star and the primary source of light and heat for Earth.",
            "topic": "Solar System & Space",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Animals that eat ONLY plants and grass are called: 🌿",
            "options": ["A) Herbivores", "B) Carnivores", "C) Omnivores", "D) Predators"],
            "correctAnswer": "A",
            "explanation": "Herbivores (like cows, deer, and rabbits) feed only on plant matter.",
            "topic": "Animal Diets",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Water boiling in a kettle turns into water vapor. This process is called: 💨",
            "options": ["A) Evaporation", "B) Freezing", "C) Melting", "D) Condensation"],
            "correctAnswer": "A",
            "explanation": "Evaporation is the phase change from liquid to gas (water vapor).",
            "topic": "Water Cycle",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "How many bones make up an adult human skeleton? 🦴",
            "options": ["A) 206", "B) 150", "C) 300", "D) 100"],
            "correctAnswer": "A",
            "explanation": "An adult human body has 206 bones in the skeletal system.",
            "topic": "Human Body",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which gas do human beings breathe IN to stay alive? 🌬️",
            "options": ["A) Oxygen", "B) Carbon Dioxide", "C) Nitrogen", "D) Helium"],
            "correctAnswer": "A",
            "explanation": "Humans inhale Oxygen for cellular respiration and exhale Carbon Dioxide.",
            "topic": "Living Things",
            "marks": 1,
        },
    ],
    "english": [
        {
            "type": "mcq",
            "questionText": "Which of the following words is a NOUN (naming word)? 📚",
            "options": ["A) School", "B) Quickly", "C) Sing", "D) Beautiful"],
            "correctAnswer": "A",
            "explanation": "A noun is the name of a person, place, or thing. 'School' is a place.",
            "topic": "Nouns & Parts of Speech",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Choose the correct article: 'Anjali eats ___ apple every morning.' 🍎",
            "options": ["A) an", "B) a", "C) the", "D) no article"],
            "correctAnswer": "A",
            "explanation": "We use 'an' before words beginning with a vowel sound (a, e, i, o, u).",
            "topic": "Articles (A, An, The)",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the plural form of the word 'Child'? 🧒",
            "options": ["A) Children", "B) Childs", "C) Childrens", "D) Childes"],
            "correctAnswer": "A",
            "explanation": "The irregular plural form of child is 'children'.",
            "topic": "Plurals",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the OPPOSITE (antonym) of the word 'Happy'? 😢",
            "options": ["A) Sad", "B) Joyful", "C) Glad", "D) Excited"],
            "correctAnswer": "A",
            "explanation": "'Sad' is the antonym of happy.",
            "topic": "Antonyms & Synonyms",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Find the ACTION word (verb) in this sentence: 'Birds fly in the blue sky.' 🕊️",
            "options": ["A) Fly", "B) Birds", "C) Sky", "D) Blue"],
            "correctAnswer": "A",
            "explanation": "'Fly' is an action verb describing what the birds are doing.",
            "topic": "Verbs & Actions",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which punctuation mark comes at the end of a question? ❓",
            "options": ["A) Question mark (?)", "B) Full stop (.)", "C) Comma (,)", "D) Exclamation mark (!)"],
            "correctAnswer": "A",
            "explanation": "A question mark (?) is placed at the end of an interrogative sentence.",
            "topic": "Punctuation",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Choose the correct spelling: 🎨",
            "options": ["A) Beautiful", "B) Beautifull", "C) Beatiful", "D) Beauteful"],
            "correctAnswer": "A",
            "explanation": "The correct spelling is 'Beautiful'.",
            "topic": "Spelling Mastery",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the past tense of the verb 'Go'? 🚶",
            "options": ["A) Went", "B) Gone", "C) Goes", "D) Going"],
            "correctAnswer": "A",
            "explanation": "The past simple form of 'go' is 'went'.",
            "topic": "Tenses",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "A word that describes a noun (like 'A red car') is called: 🚗",
            "options": ["A) Adjective", "B) Verb", "C) Pronoun", "D) Conjunction"],
            "correctAnswer": "A",
            "explanation": "An adjective describes qualities of a noun (color, size, texture).",
            "topic": "Adjectives",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the synonym (similar meaning) of the word 'Large'? 🐘",
            "options": ["A) Big", "B) Tiny", "C) Short", "D) Narrow"],
            "correctAnswer": "A",
            "explanation": "'Big' means the same as large.",
            "topic": "Synonyms",
            "marks": 1,
        },
    ]
}

# Standard Secondary / Senior Curriculum Bank (Class 5-12)
SECONDARY_QUESTION_BANKS = {
    "computer science": [
        # 1-5: MCQs (1 Mark each)
        {
            "type": "mcq",
            "questionText": "Which data structure follows the LIFO (Last In First Out) principle?",
            "options": ["A) Stack", "B) Queue", "C) Linked List", "D) Binary Tree"],
            "correctAnswer": "A",
            "explanation": "In a Stack, the element added last is the first one to be removed (LIFO).",
            "topic": "Data Structures",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "In Python, which keyword is used to define an anonymous or inline function?",
            "options": ["A) lambda", "B) def", "C) inline", "D) func"],
            "correctAnswer": "A",
            "explanation": "The 'lambda' keyword defines small anonymous functions in Python.",
            "topic": "Python Programming",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the binary representation of the decimal number 13?",
            "options": ["A) 1101", "B) 1011", "C) 1110", "D) 1001"],
            "correctAnswer": "A",
            "explanation": "13 in binary is 8 + 4 + 0 + 1 = 1101.",
            "topic": "Number Systems",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "In SQL, which clause is used to filter groups created by the GROUP BY clause?",
            "options": ["A) HAVING", "B) WHERE", "C) ORDER BY", "D) LIMIT"],
            "correctAnswer": "A",
            "explanation": "HAVING filters aggregated groups, whereas WHERE filters individual table rows.",
            "topic": "Relational Databases",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the worst-case time complexity of Binary Search on a sorted array of size n?",
            "options": ["A) O(log n)", "B) O(n)", "C) O(n log n)", "D) O(1)"],
            "correctAnswer": "A",
            "explanation": "Binary search divides the search space in half at each step, giving O(log n) time.",
            "topic": "Algorithms",
            "marks": 1,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "State De Morgan's Laws in Boolean Logic and write the algebraic equations for both laws.",
            "options": None,
            "correctAnswer": "(A + B)' = A' · B' and (A · B)' = A' + B'",
            "explanation": "De Morgan's First Law: The complement of a logical sum equals the product of individual complements (A + B)' = A' · B'. Second Law: The complement of a product equals the sum of complements (A · B)' = A' + B'.",
            "topic": "Boolean Algebra",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the difference between mutable and immutable data types in Python with one example for each.",
            "options": None,
            "correctAnswer": "Mutable types (e.g. lists, dicts) can be modified in-place; immutable types (e.g. tuples, strings, integers) cannot have their state altered after creation.",
            "explanation": "Mutable objects allow modifying element values without changing object identity (e.g., list.append()). Immutable objects generate new memory instances when modified.",
            "topic": "Python Programming",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "What is the CSS Box Model? Name its four constituent layers from inside to outside.",
            "options": None,
            "correctAnswer": "Content, Padding, Border, Margin",
            "explanation": "The CSS Box Model represents the rectangular space occupied by HTML elements, consisting of: Content (inner area), Padding (transparent inner space), Border (surrounding outline), and Margin (outer spacing).",
            "topic": "Web Technologies",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the concept of Encapsulation in Object-Oriented Programming and state one practical advantage.",
            "options": None,
            "correctAnswer": "Encapsulation is bundling data and methods into a single class unit, restricting direct access using access modifiers for data hiding and integrity.",
            "explanation": "Encapsulation safeguards internal object state from unauthorized external manipulation and decouples interface definition from implementation details.",
            "topic": "OOP Principles",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the primary differences between TCP (Transmission Control Protocol) and UDP (User Datagram Protocol).",
            "options": None,
            "correctAnswer": "TCP is connection-oriented, reliable with error checking (e.g., HTTP/FTP); UDP is connectionless and faster without delivery guarantees (e.g., video streaming/DNS).",
            "explanation": "TCP uses a three-way handshake ensuring in-order packet delivery. UDP sends packets with lower overhead, prioritizing speed over reliability.",
            "topic": "Computer Networks",
            "marks": 2,
        },
    ],
    "mathematics": [
        # 1-5: MCQs (1 Mark each)
        {
            "type": "mcq",
            "questionText": "For a quadratic equation ax² + bx + c = 0 with discriminant D = 0, the roots are:",
            "options": ["A) Two equal real roots", "B) Two distinct real roots", "C) Imaginary roots", "D) Three real roots"],
            "correctAnswer": "A",
            "explanation": "When discriminant D = b² - 4ac = 0, roots are coincident and real: x = -b/(2a).",
            "topic": "Quadratic Equations",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Find the 10th term of the Arithmetic Progression: 2, 5, 8, 11...",
            "options": ["A) 29", "B) 32", "C) 27", "D) 30"],
            "correctAnswer": "A",
            "explanation": "a = 2, d = 3. a_10 = a + (10 - 1)d = 2 + (9)(3) = 29.",
            "topic": "Arithmetic Progression",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the value of sin²(30°) + cos²(30°)?",
            "options": ["A) 1", "B) 0", "C) 1/2", "D) √3/2"],
            "correctAnswer": "A",
            "explanation": "By the Pythagorean trigonometric identity, sin²(θ) + cos²(θ) = 1 for any angle θ.",
            "topic": "Trigonometry",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "If the radius of a circle is 7 cm, calculate its circumference in cm (use π = 22/7):",
            "options": ["A) 44 cm", "B) 22 cm", "C) 88 cm", "D) 154 cm"],
            "correctAnswer": "A",
            "explanation": "Circumference = 2πr = 2 * (22/7) * 7 = 44 cm.",
            "topic": "Mensuration",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "If a fair die is rolled once, what is the probability of rolling a prime number?",
            "options": ["A) 1/2", "B) 1/3", "C) 2/3", "D) 1/6"],
            "correctAnswer": "A",
            "explanation": "Prime outcomes on a die are {2, 3, 5} -> 3 favorable out of 6 total = 3/6 = 1/2.",
            "topic": "Probability",
            "marks": 1,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Find the slope (gradient) of the line passing through the points (2, 3) and (6, 11). Show all calculation steps.",
            "options": None,
            "correctAnswer": "m = (11 - 3)/(6 - 2) = 8/4 = 2",
            "explanation": "Slope m = (y₂ - y₁) / (x₂ - x₁). Substituting coordinates: m = (11 - 3) / (6 - 2) = 8 / 4 = 2.",
            "topic": "Coordinate Geometry",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "The volume of a cube is 125 cm³. Calculate: (i) the edge length, and (ii) the total surface area of the cube.",
            "options": None,
            "correctAnswer": "Edge = 5 cm; Total Surface Area = 6 × a² = 6 × 25 = 150 cm²",
            "explanation": "Volume V = a³ = 125 ⟹ a = 5 cm. Total Surface Area = 6a² = 6 × (5)² = 150 cm².",
            "topic": "Mensuration",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Calculate the arithmetic mean of the numbers: 4, 8, 12, 16, and 20. Show the formula and step-by-step calculation.",
            "options": None,
            "correctAnswer": "Mean = Sum / Count = (4 + 8 + 12 + 16 + 20) / 5 = 60 / 5 = 12",
            "explanation": "Mean x̄ = (∑x) / n. Sum = 4 + 8 + 12 + 16 + 20 = 60. Count n = 5. Mean = 60 / 5 = 12.",
            "topic": "Statistics",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Solve the linear equation for x: 3x - 7 = 14. Show all algebraic transposition steps.",
            "options": None,
            "correctAnswer": "3x = 14 + 7 ⟹ 3x = 21 ⟹ x = 7",
            "explanation": "Add 7 to both sides: 3x = 21. Divide by 3: x = 21 / 3 = 7.",
            "topic": "Linear Equations",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State Pythagoras Theorem and calculate the length of the hypotenuse in a right triangle with perpendicular sides 6 cm and 8 cm.",
            "options": None,
            "correctAnswer": "Hypotenuse = √(6² + 8²) = √(36 + 64) = √100 = 10 cm",
            "explanation": "Pythagoras Theorem: In a right triangle, h² = p² + b². h = √(6² + 8²) = √100 = 10 cm.",
            "topic": "Pythagoras Theorem",
            "marks": 2,
        },
    ],
    "english": [
        # 1-5: MCQs (1 Mark each)
        {
            "type": "mcq",
            "questionText": "Identify the passive voice for: 'The chef prepared a magnificent dinner.'",
            "options": [
                "A) A magnificent dinner was prepared by the chef.",
                "B) A magnificent dinner is being prepared by the chef.",
                "C) The chef was preparing dinner.",
                "D) Dinner has been prepared by chef."
            ],
            "correctAnswer": "A",
            "explanation": "Simple past active 'prepared' transforms to 'was prepared' in passive voice.",
            "topic": "Active and Passive Voice",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which of the following is a complex sentence?",
            "options": [
                "A) Although it was raining, we decided to play outside.",
                "B) She bought apples and oranges from the grocery store.",
                "C) The train arrived on time.",
                "D) He worked hard, so he passed the exam."
            ],
            "correctAnswer": "A",
            "explanation": "A complex sentence contains one independent clause and at least one dependent clause introduced by a subordinating conjunction ('Although').",
            "topic": "Sentence Structures",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Choose the correct indirect speech for: He said, 'I am reading a novel.'",
            "options": [
                "A) He said that he was reading a novel.",
                "B) He says that he is reading a novel.",
                "C) He said that he read a novel.",
                "D) He told that he had read a novel."
            ],
            "correctAnswer": "A",
            "explanation": "Present continuous 'am reading' shifts to past continuous 'was reading' in reported speech.",
            "topic": "Direct & Indirect Speech",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What figure of speech is used in: 'The classroom was a zoo during the break'?",
            "options": ["A) Metaphor", "B) Simile", "C) Personification", "D) Hyperbole"],
            "correctAnswer": "A",
            "explanation": "A metaphor directly equates one thing to another without using 'like' or 'as'.",
            "topic": "Figures of Speech",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Select the antonym for the word 'Candid':",
            "options": ["A) Deceitful", "B) Honest", "C) Frank", "D) Sincere"],
            "correctAnswer": "A",
            "explanation": "'Candid' means truthful and straightforward; its antonym is 'Deceitful'.",
            "topic": "Vocabulary & Antonyms",
            "marks": 1,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Explain the meaning of the idiom 'Bite the bullet' and write a meaningful sentence using it.",
            "options": None,
            "correctAnswer": "Meaning: To face a difficult or unpleasant situation with courage. Example: She decided to bite the bullet and apologize for her mistake.",
            "explanation": "'Bite the bullet' originated from soldiers biting on lead bullets during surgery without anesthesia. It signifies confronting unavoidable hardship bravely.",
            "topic": "Idioms and Phrases",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the difference in usage between the modal auxiliary verbs 'Must' and 'Might' with one example for each.",
            "options": None,
            "correctAnswer": "'Must' indicates strong obligation, necessity, or certainty (e.g., 'You must wear a seatbelt'). 'Might' indicates weak possibility or uncertainty (e.g., 'It might rain today').",
            "explanation": "'Must' expresses mandatory rules or high probability, whereas 'Might' expresses tentative possibilities.",
            "topic": "Modal Auxiliaries",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Identify the complete Subject and Predicate in the inverted sentence: 'Under the old wooden bridge lives a family of otters.'",
            "options": None,
            "correctAnswer": "Subject: 'A family of otters'; Predicate: 'lives under the old wooden bridge'",
            "explanation": "In inverted sentences, the entity performing the verb action ('a family of otters') is the subject, while the prepositional phrase and verb form the predicate.",
            "topic": "Subject-Verb Agreement",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain how the negative prefixes 'Il-', 'Im-', and 'Un-' change the meaning of root words, giving one example for each.",
            "options": None,
            "correctAnswer": "They create antonyms by denoting negation/absence: 'Il-' + Legible = Illegible; 'Im-' + Possible = Impossible; 'Un-' + Happy = Unhappy.",
            "explanation": "Prefixes modify word polarity: 'Il-' applies before 'l', 'Im-' before 'm'/'p', and 'Un-' as a general English negation prefix.",
            "topic": "Prefixes & Suffixes",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Define an Adjective Clause and write a sentence that contains an adjective clause qualifying a noun.",
            "options": None,
            "correctAnswer": "Definition: A dependent clause that modifies a noun or pronoun. Example: 'The student who worked diligently scored highest in the exam.'",
            "explanation": "Adjective clauses are introduced by relative pronouns (who, which, that, whose) and describe attributes of an antecedent noun.",
            "topic": "Clauses and Grammar",
            "marks": 2,
        },
    ],
    "science": [
        # 1-5: MCQs (1 Mark each)
        {
            "type": "mcq",
            "questionText": "Which cell organelle is commonly referred to as the 'Powerhouse of the Cell'?",
            "options": ["A) Mitochondria", "B) Ribosome", "C) Golgi Apparatus", "D) Nucleus"],
            "correctAnswer": "A",
            "explanation": "Mitochondria generate cellular energy in the form of ATP through cellular respiration.",
            "topic": "Cell Biology",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the chemical formula of common baking soda?",
            "options": ["A) NaHCO₃", "B) Na₂CO₃", "C) NaCl", "D) NaOH"],
            "correctAnswer": "A",
            "explanation": "Sodium hydrogen carbonate (Sodium Bicarbonate, NaHCO₃) is baking soda.",
            "topic": "Acids, Bases & Salts",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which law of motion gives the fundamental definition of Force as F = ma?",
            "options": [
                "A) Newton's Second Law",
                "B) Newton's First Law",
                "C) Newton's Third Law",
                "D) Law of Gravitation"
            ],
            "correctAnswer": "A",
            "explanation": "Newton's Second Law states that the rate of change of momentum is proportional to applied force (F = ma).",
            "topic": "Laws of Motion",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which metal remains in liquid state at standard room temperature?",
            "options": ["A) Mercury (Hg)", "B) Sodium (Na)", "C) Lead (Pb)", "D) Gallium (Ga)"],
            "correctAnswer": "A",
            "explanation": "Mercury is the only elemental metal that is liquid at standard room temperature (25°C).",
            "topic": "Metals and Non-Metals",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "The phenomenon of splitting white light into its component colors through a prism is called:",
            "options": ["A) Dispersion", "B) Refraction", "C) Total Internal Reflection", "D) Diffraction"],
            "correctAnswer": "A",
            "explanation": "Dispersion is the separation of white light into its spectrum of colors due to varying wavelengths.",
            "topic": "Light and Optics",
            "marks": 1,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Explain why the pH of pure distilled water is 7.0 at 25°C and state what happens to the ion product of water (Kw) when temperature increases.",
            "options": None,
            "correctAnswer": "In pure water at 25°C, [H⁺] = [OH⁻] = 1.0 × 10⁻⁷ M, hence pH = -log(10⁻⁷) = 7.0 (neutral). As temperature increases, auto-ionization of water is endothermic, so Kw increases.",
            "explanation": "Water self-ionizes: H₂O ⇌ H⁺ + OH⁻. At 25°C, equal concentrations yield neutral pH 7. Increasing temperature shifts equilibrium rightward, increasing Kw.",
            "topic": "Chemical Equilibrium",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Why is blood group O-negative termed the 'Universal Donor'? Explain with respect to RBC surface antigens and transfusion compatibility.",
            "options": None,
            "correctAnswer": "O-negative red blood cells lack A, B, and Rh (D) surface antigens, so recipient antibodies will not trigger agglutination/immune rejection.",
            "explanation": "Because O- RBCs carry no A, B, or Rh surface agglutinogens, they can safely be transfused into any ABO/Rh blood group recipient in emergencies.",
            "topic": "Circulatory System",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State the working principle of an Ammeter and explain why it must always be connected in series in an electric circuit.",
            "options": None,
            "correctAnswer": "An ammeter measures electric current and has very low internal resistance. It is connected in series so the full circuit current passes through it without significantly reducing current flow.",
            "explanation": "If connected in parallel, its low resistance would create a short circuit and draw excessive current, potentially damaging the circuit.",
            "topic": "Electricity & Magnetism",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain why the combustion of methane gas (CH₄) is classified as an exothermic chemical reaction. Write the balanced chemical equation.",
            "options": None,
            "correctAnswer": "Equation: CH₄(g) + 2O₂(g) ⟶ CO₂(g) + 2H₂O(g) + Heat. It is exothermic because energy released in bond formation in products exceeds energy needed to break reactant bonds.",
            "explanation": "Combustion releases thermal and radiant energy to the surroundings (negative ΔH), characterizing exothermic reactions.",
            "topic": "Chemical Reactions",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Describe the biological significance of the Ozone Layer (O₃) in the Stratosphere and state two consequences of ozone depletion on human health.",
            "options": None,
            "correctAnswer": "Significance: Absorbs harmful high-energy solar UV-B radiation. Consequences: Increased incidence of skin cancers/melanoma and cataracts/eye damage.",
            "explanation": "Stratospheric ozone shields terrestrial organisms from lethal UV-B radiation. Depletion impairs cellular DNA in biological tissues.",
            "topic": "Environmental Science",
            "marks": 2,
        },
    ],
    "social studies": [
        # 1-5: MCQs (1 Mark each)
        {
            "type": "mcq",
            "questionText": "Who is revered as the 'Father of the Indian Constitution'?",
            "options": ["A) Dr. B.R. Ambedkar", "B) Mahatma Gandhi", "C) Jawaharlal Nehru", "D) Sardar Vallabhbhai Patel"],
            "correctAnswer": "A",
            "explanation": "Dr. Bhimrao Ramji Ambedkar served as the Chairman of the Drafting Committee of the Constitution of India.",
            "topic": "Indian Polity & Constitution",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which imaginary line divides the Earth into the Northern and Southern Hemispheres?",
            "options": ["A) Equator (0° Latitude)", "B) Prime Meridian (0° Longitude)", "C) Tropic of Cancer", "D) Tropic of Capricorn"],
            "correctAnswer": "A",
            "explanation": "The Equator is the 0° parallel of latitude dividing Earth into Northern and Southern halves.",
            "topic": "Physical Geography",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "In which year did the historic Revolt of 1857 (Sepoy Mutiny) break out in India?",
            "options": ["A) 1857", "B) 1757", "C) 1947", "D) 1885"],
            "correctAnswer": "A",
            "explanation": "The first major armed uprising against British East India Company rule began in 1857 at Meerut.",
            "topic": "Modern Indian History",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which tier of government in India operates at the local village grassroots level?",
            "options": ["A) Gram Panchayat (Panchayati Raj)", "B) Municipal Corporation", "C) State Legislature", "D) Parliament"],
            "correctAnswer": "A",
            "explanation": "The 73rd Constitutional Amendment Act established the 3-tier Panchayati Raj system with Gram Panchayat at the village base.",
            "topic": "Local Self Government",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which is the longest river in peninsular India?",
            "options": ["A) Godavari", "B) Krishna", "C) Narmada", "D) Kaveri"],
            "correctAnswer": "A",
            "explanation": "The Godavari River is known as 'Dakshin Ganga' and is the longest peninsular river in India (approx 1,465 km).",
            "topic": "Drainage Systems",
            "marks": 1,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Explain the significance of Fundamental Rights enshrined in Part III of the Indian Constitution.",
            "options": None,
            "correctAnswer": "Fundamental Rights (Articles 12-35) protect individual liberties, equality, and dignity against arbitrary state action, enforceable via High Courts and Supreme Court (Article 32).",
            "explanation": "They guarantee civil liberties such as Equality, Freedom of Speech, Protection from Exploitation, and Constitutional Remedies for democratic justice.",
            "topic": "Indian Civics",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State two major geographical and economic factors that led to the onset of the Industrial Revolution in 18th-century Britain.",
            "options": None,
            "correctAnswer": "1. Abundant coal and iron ore deposits close to water transport routes. 2. Technological innovations (steam engine, spinning jenny) coupled with capital from colonial trade.",
            "explanation": "Britain possessed natural resources, capital wealth, naval dominance, and a stable patent legal system accelerating mechanization.",
            "topic": "World History",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain why Black Soil (Regur Soil) of the Deccan Plateau is ideal for cotton cultivation.",
            "options": None,
            "correctAnswer": "Black soil is fine-textured, clayey, rich in calcium carbonate, magnesium, and potash, with exceptional moisture-retention capacity essential for cotton maturation.",
            "explanation": "Originating from volcanic lava weathering, its moisture-holding and deep cracking properties aerate the soil, providing ideal conditions for cotton crops.",
            "topic": "Resources & Agriculture",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the administrative and strategic role of Chanakya (Kautilya) in the establishment of the Maurya Empire.",
            "options": None,
            "correctAnswer": "Chanakya mentored Chandragupta Maurya, devised political alliances to overthrow the Nanda Dynasty, and authored the Arthashastra establishing statecraft governance.",
            "explanation": "Chanakya's economic treaties, espionage networks, and military diplomacy laid the institutional foundation of India's first unified empire.",
            "topic": "Ancient History",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "What is the importance of Universal Adult Suffrage in a democratic nation like India?",
            "options": None,
            "correctAnswer": "It grants every citizen aged 18+ the right to vote without discrimination of caste, religion, gender, or wealth, upholding political equality and people's sovereignty.",
            "explanation": "Guaranteed under Article 326 of the Constitution, it ensures representative democracy and accountability of elected governments.",
            "topic": "Elections & Democracy",
            "marks": 2,
        },
    ],
    "logical reasoning": [
        # 1-5: MCQs (1 Mark each)
        {
            "type": "mcq",
            "questionText": "Find the next number in the series: 3, 6, 12, 24, 48, ___",
            "options": ["A) 96", "B) 72", "C) 84", "D) 100"],
            "correctAnswer": "A",
            "explanation": "Each number is multiplied by 2. 48 × 2 = 96.",
            "topic": "Number Series",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "If BOOK is coded as 43, what is the code for PEN (P=16, E=5, N=14)?",
            "options": ["A) 35", "B) 32", "C) 40", "D) 30"],
            "correctAnswer": "A",
            "explanation": "Sum of alphabetical positions: 16 + 5 + 14 = 35.",
            "topic": "Coding-Decoding",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Pointing to a photograph, Rohit said, 'She is the mother of my father's only son.' Who is she to Rohit?",
            "options": ["A) Mother", "B) Sister", "C) Aunt", "D) Grandmother"],
            "correctAnswer": "A",
            "explanation": "Rohit's father's only son is Rohit himself. Her mother is Rohit's mother.",
            "topic": "Blood Relations",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "A clock shows 3:00. What is the angle between the hour hand and the minute hand?",
            "options": ["A) 90°", "B) 60°", "C) 120°", "D) 45°"],
            "correctAnswer": "A",
            "explanation": "At 3:00, the minute hand is at 12 and the hour hand is at 3, creating a 90° right angle.",
            "topic": "Clock Problems",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Choose the odd one out:",
            "options": ["A) Triangle", "B) Square", "C) Rectangle", "D) Circle"],
            "correctAnswer": "D",
            "explanation": "Circle is curved, while Triangle, Square, and Rectangle are polygons made of straight line segments.",
            "topic": "Classification",
            "marks": 1,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "If South-East becomes North, and North-East becomes West, explain what direction 'West' will become. Show your angle rotation deduction.",
            "options": None,
            "correctAnswer": "West becomes South-East. Deduction: The compass shifts 135° clockwise. Rotating West by 135° clockwise yields South-East.",
            "explanation": "Angle between South-East and North is 135° clockwise. Applying a 135° clockwise rotation to West leads to South-East.",
            "topic": "Direction Sense",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "In a class row of 25 students, Priya ranks 10th from the left end. Calculate her rank from the right end and show the ranking formula.",
            "options": None,
            "correctAnswer": "Rank from Right = (Total Students - Rank from Left) + 1 = (25 - 10) + 1 = 16th",
            "explanation": "Formula: Total = Left_Rank + Right_Rank - 1 ⟹ Right_Rank = 25 - 10 + 1 = 16th.",
            "topic": "Order & Ranking",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the semantic relationship in the analogy 'Doctor : Hospital :: Teacher : School' and formulate another pair with the same relationship.",
            "options": None,
            "correctAnswer": "Relationship: Professional to their primary Workplace. New example: 'Judge : Court' or 'Scientist : Laboratory'.",
            "explanation": "The analogy represents Person : Place of Work. Doctors practice in hospitals, and teachers instruct in schools.",
            "topic": "Analogies",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Given Premises: (1) All squares are rectangles. (2) All rectangles are quadrilaterals. State the logical deductive conclusion regarding squares and explain why.",
            "options": None,
            "correctAnswer": "Conclusion: All squares are quadrilaterals. Reason: By the transitive property of categorical syllogisms (A ⊆ B and B ⊆ C ⟹ A ⊆ C).",
            "explanation": "Since the subset of squares is entirely contained within rectangles, and rectangles within quadrilaterals, every square is necessarily a quadrilateral.",
            "topic": "Syllogisms & Logic",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "If arithmetic operator symbols are coded as '+' means '×', '×' means '÷', and '÷' means '+', evaluate the expression: 8 + 4 ÷ 6 × 2. Show step-by-step BODMAS evaluation.",
            "options": None,
            "correctAnswer": "Replaced expression: 8 × 4 + (6 ÷ 2) = 32 + 3 = 35",
            "explanation": "Substituting operators gives 8 × 4 + 6 ÷ 2. By BODMAS order: 6 ÷ 2 = 3; 8 × 4 = 32; 32 + 3 = 35.",
            "topic": "Mathematical Operations",
            "marks": 2,
        },
    ],
    "science": [
        # 1-5: MCQs (1 Mark each)
        {
            "type": "mcq",
            "questionText": "Which organelle is considered the powerhouse of eukaryotic cells?",
            "options": ["A) Mitochondria", "B) Ribosome", "C) Golgi apparatus", "D) Endoplasmic reticulum"],
            "correctAnswer": "A",
            "explanation": "Mitochondria generate most of the cell's supply of ATP through cellular respiration.",
            "topic": "Cell Structure",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What is the SI unit of Electric Current?",
            "options": ["A) Ampere (A)", "B) Volt (V)", "C) Ohm (Ω)", "D) Coulomb (C)"],
            "correctAnswer": "A",
            "explanation": "The SI base unit of electric current is the Ampere (A).",
            "topic": "Electricity & Magnetism",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "What type of chemical reaction occurs when Calcium Carbonate decomposes into CaO and CO₂ upon heating?",
            "options": ["A) Thermal Decomposition", "B) Combination Reaction", "C) Displacement Reaction", "D) Neutralization"],
            "correctAnswer": "A",
            "explanation": "CaCO₃(s) -> CaO(s) + CO₂(g) is a thermal decomposition reaction driven by heat.",
            "topic": "Chemical Reactions",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "Which part of the human brain controls involuntary actions like heartbeat and breathing?",
            "options": ["A) Medulla Oblongata", "B) Cerebrum", "C) Cerebellum", "D) Hypothalamus"],
            "correctAnswer": "A",
            "explanation": "The medulla oblongata in the brainstem regulates vital autonomous functions like heartbeat and breathing.",
            "topic": "Control & Coordination",
            "marks": 1,
        },
        {
            "type": "mcq",
            "questionText": "An object placed at 2F in front of a convex lens produces an image that is:",
            "options": ["A) Real, inverted, and same size at 2F", "B) Virtual and magnified", "C) Real and diminished at F", "D) Highly magnified at infinity"],
            "correctAnswer": "A",
            "explanation": "When placed at 2F of a convex lens, a real, inverted image of identical size forms at 2F on the other side.",
            "topic": "Light & Optics",
            "marks": 1,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "State Ohm's Law and write the mathematical relationship between Voltage (V), Current (I), and Resistance (R).",
            "options": None,
            "correctAnswer": "Ohm's Law: Current flowing through a conductor is directly proportional to the potential difference across its ends at constant temperature. V = I × R.",
            "explanation": "V = IR, where V is potential difference in Volts, I is current in Amperes, and R is resistance in Ohms.",
            "topic": "Electricity",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Differentiate between Exothermic and Endothermic chemical reactions with one chemical equation for each.",
            "options": None,
            "correctAnswer": "Exothermic releases heat (e.g., C + O₂ -> CO₂ + Heat). Endothermic absorbs heat (e.g., CaCO₃ + Heat -> CaO + CO₂).",
            "explanation": "Exothermic reactions release thermal energy (ΔH < 0), while endothermic reactions absorb heat from surroundings (ΔH > 0).",
            "topic": "Chemical Reactions",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the role of Bile Juice in human digestion and state where it is produced and stored.",
            "options": None,
            "correctAnswer": "Bile juice emulsifies large fat globules into smaller droplets and makes the medium alkaline for pancreatic enzymes. Produced by Liver, stored in Gallbladder.",
            "explanation": "Bile salts lower surface tension to emulsify lipids for lipase action. Synthesized in liver hepatocytes.",
            "topic": "Life Processes",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State Snell's Law of refraction and write the mathematical formula for refractive index.",
            "options": None,
            "correctAnswer": "Snell's Law: The ratio of sine of angle of incidence to sine of angle of refraction is constant for a given pair of media. sin(i) / sin(r) = n₂ / n₁.",
            "explanation": "Refractive index n = c/v = sin(i)/sin(r).",
            "topic": "Light Refraction",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "What is the function of the Ozone layer in Earth's stratosphere, and which chemical compounds cause its depletion?",
            "options": None,
            "correctAnswer": "The ozone layer (O₃) shields life by absorbing harmful UV-B radiation from the sun. Depleted primarily by Chlorofluorocarbons (CFCs).",
            "explanation": "Chlorofluorocarbons release chlorine radicals upon UV exposure which catalyze the breakdown of O₃ molecules into O₂.",
            "topic": "Our Environment",
            "marks": 2,
        },
    ],
}

# Senior Secondary & Competitive Exam Bank (Class 11, Class 12, ISC, CBSE, NEET, JEE)
# 10 Questions @ 2 Marks = 20 Marks Total
SENIOR_SECONDARY_BANKS = {
    "chemistry": [
        # 1-5: MCQs (2 Marks each)
        {
            "type": "mcq",
            "questionText": "For a zero-order reaction A -> Products, what is the integrated rate equation and the half-life period (t₁/₂)?",
            "options": [
                "A) [A] = [A]₀ - kt and t₁/₂ = [A]₀ / (2k)",
                "B) ln[A] = ln[A]₀ - kt and t₁/₂ = 0.693 / k",
                "C) 1/[A] - 1/[A]₀ = kt and t₁/₂ = 1 / (k[A]₀)",
                "D) [A] = [A]₀ e^(-kt) and t₁/₂ = 2[A]₀ / k"
            ],
            "correctAnswer": "A",
            "explanation": "For zero-order kinetics: rate = -d[A]/dt = k ⟹ [A] = [A]₀ - kt. When [A] = [A]₀/2, t₁/₂ = [A]₀/(2k).",
            "topic": "Chemical Kinetics",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Which coordination complex exhibits optical isomerism (chirality)?",
            "options": [
                "A) [Co(en)₃]³⁺",
                "B) trans-[Pt(NH₃)₂Cl₂]",
                "C) [Co(NH₃)₆]³⁺",
                "D) [Ni(CN)₄]²⁻"
            ],
            "correctAnswer": "A",
            "explanation": "Tris-(ethylenediamine)cobalt(III) [Co(en)₃]³⁺ lacks a plane of symmetry (D3 point group) and exists as non-superimposable d- and l- enantiomers.",
            "topic": "Coordination Compounds",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "In the SN2 nucleophilic substitution mechanism, the stereochemical outcome is characterized by:",
            "options": [
                "A) Complete Walden inversion of configuration",
                "B) Racemization with slight inversion",
                "C) 100% Retention of configuration",
                "D) Carbocation rearrangement"
            ],
            "correctAnswer": "A",
            "explanation": "SN2 reactions occur via a concerted backside nucleophilic attack, producing complete stereochemical inversion (Walden inversion).",
            "topic": "Organic Reaction Mechanisms",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "According to the Nernst Equation, what is the cell potential E_cell at 298 K for the Daniell Cell Zn | Zn²⁺(0.1 M) || Cu²⁺(1.0 M) | Cu (E°_cell = 1.10 V)?",
            "options": [
                "A) 1.130 V",
                "B) 1.070 V",
                "C) 1.100 V",
                "D) 0.980 V"
            ],
            "correctAnswer": "A",
            "explanation": "E_cell = E° - (0.0591/2) * log([Zn²⁺]/[Cu²⁺]) = 1.10 - 0.02955 * log(0.1/1.0) = 1.10 - 0.02955 * (-1) = 1.10 + 0.02955 ≈ 1.13 V.",
            "topic": "Electrochemistry",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Which colligative property measurement is most suitable for determining the molar mass of biomolecules and polymers?",
            "options": [
                "A) Osmotic Pressure",
                "B) Elevation in Boiling Point",
                "C) Depression in Freezing Point",
                "D) Relative Lowering of Vapor Pressure"
            ],
            "correctAnswer": "A",
            "explanation": "Osmotic pressure can be measured accurately at room temperature with high sensitivity for dilute solutions of high-molar-mass polymers.",
            "topic": "Solutions & Colligative Properties",
            "marks": 2,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "State Raoult's Law for a binary solution containing two volatile liquid components A and B, and write the mathematical expression for total vapor pressure.",
            "options": None,
            "correctAnswer": "Raoult's Law: The partial vapor pressure of each volatile component in a solution is directly proportional to its mole fraction: P_total = P_A°·x_A + P_B°·x_B.",
            "explanation": "P_total = P_A + P_B = P_A°·x_A + P_B°·(1 - x_A) for an ideal solution where intermolecular forces between unlike molecules equal those between like molecules.",
            "topic": "Solutions",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain Cannizzaro Reaction with a balanced chemical equation using Benzaldehyde (C₆H₅CHO).",
            "options": None,
            "correctAnswer": "Aldehydes lacking α-hydrogen atoms undergo self-redox (disproportionation) in concentrated alkali: 2 C₆H₅CHO + NaOH -> C₆H₅COONa + C₆H₅CH₂OH (Sodium Benzoate + Benzyl Alcohol).",
            "explanation": "One molecule of benzaldehyde is reduced to benzyl alcohol while the second molecule is oxidized to sodium benzoate in 50% NaOH.",
            "topic": "Aldehydes, Ketones & Carboxylic Acids",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State Kohlrausch's Law of Independent Migration of Ions and write its expression for the limiting molar conductivity of MgCl₂ (Λ°_m(MgCl₂)).",
            "options": None,
            "correctAnswer": "Kohlrausch's Law states limiting molar conductivity of an electrolyte equals the sum of individual limiting molar conductivities of its cations and anions. Λ°_m(MgCl₂) = λ°(Mg²⁺) + 2·λ°(Cl⁻).",
            "explanation": "At infinite dilution, each ion migrates independently unaffected by the co-ion.",
            "topic": "Electrochemistry",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Using Crystal Field Theory (CFT), explain why [Fe(CN)₆]³⁻ is low spin (inner orbital) while [FeF₆]³⁻ is high spin (outer orbital).",
            "options": None,
            "correctAnswer": "CN⁻ is a strong field ligand causing large crystal field splitting (Δo > P), forcing d-electrons to pair up (t2g⁵ eg⁰, low spin, 1 unpaired electron). F⁻ is a weak field ligand (Δo < P) yielding high spin (t2g³ eg², 5 unpaired electrons).",
            "explanation": "Strong field ligands exceed electron pairing energy P, resulting in lower total spin configuration.",
            "topic": "Coordination Compounds",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Define the Arrhenius activation energy (Ea) and write the logarithmic form of the Arrhenius equation comparing rate constants k₁ and k₂ at temperatures T₁ and T₂.",
            "options": None,
            "correctAnswer": "Activation Energy (Ea) is the minimum energy required by reacting molecules to form the activated complex. ln(k₂/k₁) = (Ea/R) × [(T₂ - T₁)/(T₁·T₂)].",
            "explanation": "Arrhenius equation k = A·e^(-Ea/RT). Logarithmic form: log(k₂/k₁) = (Ea / 2.303R) * (1/T₁ - 1/T₂).",
            "topic": "Chemical Kinetics",
            "marks": 2,
        },
    ],
    "physics": [
        # 1-5: MCQs (2 Marks each)
        {
            "type": "mcq",
            "questionText": "What is the magnetic force on a charge q moving with velocity v in a uniform magnetic field B?",
            "options": [
                "A) F = q(v × B)",
                "B) F = q(v · B)",
                "C) F = (v × B) / q",
                "D) F = q²(v × B)"
            ],
            "correctAnswer": "A",
            "explanation": "The Lorentz magnetic force vector is F = q(v × B) with magnitude F = qvB sin(θ).",
            "topic": "Magnetic Effects of Current",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "In Young's Double Slit Experiment (YDSE), if the screen distance D is doubled and slit separation d is halved, the fringe width β becomes:",
            "options": [
                "A) 4 times original",
                "B) 2 times original",
                "C) Halved",
                "D) Unchanged"
            ],
            "correctAnswer": "A",
            "explanation": "Fringe width β = λD / d. If D' = 2D and d' = d/2, then β' = λ(2D)/(d/2) = 4(λD/d) = 4β.",
            "topic": "Wave Optics",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "According to Einstein's Photoelectric Equation, the maximum kinetic energy (K_max) of emitted photoelectrons equals:",
            "options": [
                "A) hν - Φ₀ (where Φ₀ is work function)",
                "B) hν + Φ₀",
                "C) Φ₀ / hν",
                "D) 0.5 hν"
            ],
            "correctAnswer": "A",
            "explanation": "Einstein's photoelectric law: K_max = hν - Φ₀ = h(ν - ν₀), where hν is incident photon energy and Φ₀ is work function.",
            "topic": "Dual Nature of Radiation",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "An alternating current circuit contains an inductor L and capacitor C in series. The resonant angular frequency ω₀ is given by:",
            "options": [
                "A) 1 / √(LC)",
                "B) √(LC)",
                "C) L / C",
                "D) 1 / (2πLC)"
            ],
            "correctAnswer": "A",
            "explanation": "At resonance, inductive reactance equals capacitive reactance: ωL = 1/(ωC) ⟹ ω₀ = 1 / √(LC).",
            "topic": "Alternating Current",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "What is the de Broglie wavelength λ of an electron accelerated through a potential difference of V volts?",
            "options": [
                "A) λ = 1.227 / √V nm",
                "B) λ = 12.27 / V nm",
                "C) λ = √V / 1.227 nm",
                "D) λ = 0.1227 / √V nm"
            ],
            "correctAnswer": "A",
            "explanation": "λ = h / p = h / √(2m_e eV) = 1.227 / √V nanometers.",
            "topic": "Quantum & Modern Physics",
            "marks": 2,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "State Gauss's Law in Electrostatics and express it in integral vector notation for a closed Gaussian surface enclosing charge Q_enc.",
            "options": None,
            "correctAnswer": "Gauss's Law states that total electric flux through any closed surface equals (1/ε₀) times the net enclosed charge: ∮ E · dA = Q_enc / ε₀.",
            "explanation": "∮ E · dA = Q_enc / ε₀ where E is electric field vector, dA is area element vector, and ε₀ is permittivity of free space.",
            "topic": "Electrostatics",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State Faraday's Law of Electromagnetic Induction and Lenz's Law, giving the mathematical formula for induced EMF.",
            "options": None,
            "correctAnswer": "Faraday's Law: Induced EMF is proportional to time rate of change of magnetic flux. Lenz's Law: Direction of induced current opposes the flux change causing it. ε = - dΦ_B / dt.",
            "explanation": "ε = -N (dΦ_B / dt), where negative sign embodies Lenz's law (conservation of energy).",
            "topic": "Electromagnetic Induction",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Derive the expression for the equivalent capacitance (C_eq) of two capacitors C₁ and C₂ connected in series.",
            "options": None,
            "correctAnswer": "In series, charge Q is identical across both capacitors: V = V₁ + V₂ = Q/C₁ + Q/C₂ = Q(1/C₁ + 1/C₂). Therefore 1/C_eq = 1/C₁ + 1/C₂ ⟹ C_eq = (C₁·C₂)/(C₁ + C₂).",
            "explanation": "Reciprocal of equivalent series capacitance is the sum of reciprocals of individual capacitances.",
            "topic": "Capacitance",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State Biot-Savart Law and write the vector equation for magnetic field dB produced by a current element I·dl at displacement r.",
            "options": None,
            "correctAnswer": "Biot-Savart Law gives magnetic field produced by current element: dB = (μ₀ / 4π) · (I dl × r̂) / r² = (μ₀ / 4π) · (I dl × r) / r³.",
            "explanation": "μ₀ is permeability of free space (4π × 10⁻⁷ T·m/A). Magnitude dB = (μ₀/4π) * (I dl sin θ / r²).",
            "topic": "Magnetism & Current",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the principle of Total Internal Reflection (TIR) and define critical angle (θ_c) with formula in terms of refractive indices n₁ and n₂ (n₁ > n₂).",
            "options": None,
            "correctAnswer": "TIR occurs when light traveling from a denser medium (n₁) to rarer medium (n₂) strikes the interface at angle greater than critical angle θ_c: sin(θ_c) = n₂ / n₁.",
            "explanation": "At critical angle θ_c, angle of refraction is 90°. When i > θ_c, 100% of light reflects back into the denser medium.",
            "topic": "Ray Optics",
            "marks": 2,
        },
    ],
    "biology": [
        # 1-5: MCQs (2 Marks each)
        {
            "type": "mcq",
            "questionText": "In DNA replication, which enzyme synthesizes RNA primers required for DNA Polymerase III to initiate elongation?",
            "options": ["A) RNA Primase", "B) DNA Helicase", "C) DNA Ligase", "D) Topoisomerase"],
            "correctAnswer": "A",
            "explanation": "RNA Primase synthesizes short complementary RNA primers providing the free 3'-OH group needed by DNA polymerase.",
            "topic": "Molecular Genetics",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "In Polymerase Chain Reaction (PCR), what is the correct sequence of thermal cycling steps?",
            "options": [
                "A) Denaturation (~94°C) -> Annealing (~55°C) -> Extension (~72°C)",
                "B) Annealing -> Denaturation -> Extension",
                "C) Extension -> Denaturation -> Annealing",
                "D) Denaturation -> Extension -> Annealing"
            ],
            "correctAnswer": "A",
            "explanation": "PCR cycles through: (1) Denaturation to separate DNA strands at 94-96°C, (2) Primer annealing at 50-60°C, (3) Taq polymerase extension at 72°C.",
            "topic": "Biotechnology",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Which hormone surge triggers ovulation and the release of the secondary oocyte from the Graafian follicle?",
            "options": ["A) Luteinizing Hormone (LH surge)", "B) Progesterone", "C) Estrogen", "D) Prolactin"],
            "correctAnswer": "A",
            "explanation": "A sharp mid-cycle LH surge (around Day 14) induces rupture of the mature Graafian follicle and ovulation.",
            "topic": "Human Reproduction",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "In a dihybrid cross following Mendel's Law of Independent Assortment, what is the classic phenotypic ratio in the F2 generation?",
            "options": ["A) 9:3:3:1", "B) 1:2:1", "C) 3:1", "D) 9:7"],
            "correctAnswer": "A",
            "explanation": "Mendelian dihybrid phenotypic ratio in F2 generation of heterozygous parents (AaBb x AaBb) is 9:3:3:1.",
            "topic": "Principles of Inheritance",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Which immunoglobulins (antibodies) are found predominantly in maternal colostrum, providing passive immunity to the newborn?",
            "options": ["A) Secretory IgA", "B) IgM", "C) IgE", "D) IgD"],
            "correctAnswer": "A",
            "explanation": "IgA antibodies in colostrum coat mucosal linings of the infant gastrointestinal tract to shield against pathogens.",
            "topic": "Human Health & Immunology",
            "marks": 2,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Explain the Central Dogma of Molecular Biology proposed by Francis Crick and state the process that violates it in retroviruses.",
            "options": None,
            "correctAnswer": "Central Dogma: DNA -> (Transcription) -> mRNA -> (Translation) -> Protein. Retroviruses violate this via Reverse Transcription (RNA -> complementary DNA catalyzed by Reverse Transcriptase).",
            "explanation": "Information flows unidirectionally from nucleic acids to functional proteins; retroviruses (e.g. HIV) transcribe RNA into cDNA.",
            "topic": "Molecular Biology",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Define Restriction Endonucleases and explain why they are called 'Molecular Scissors' in recombinant DNA technology.",
            "options": None,
            "correctAnswer": "Restriction Endonucleases are bacterial enzymes that recognize specific palindromic DNA sequences and cleave phosphodiester bonds, generating sticky or blunt ends for gene splicing.",
            "explanation": "Discovered in bacteria as defense against bacteriophages; widely used to cut plasmid vectors and donor genes at targeted loci.",
            "topic": "Biotechnology Principles",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Differentiate between Homologous and Analogous organs with one evolutionary example of each.",
            "options": None,
            "correctAnswer": "Homologous organs share common anatomical origin but perform different functions (Divergent evolution, e.g., human arm and bat wing). Analogous organs share similar function with different anatomical origins (Convergent evolution, e.g., bird wing and butterfly wing).",
            "explanation": "Homology indicates common phylogenetic ancestry; analogy results from similar ecological selection pressures.",
            "topic": "Evolution",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the 10% Law of Energy Transfer in trophic ecological food chains proposed by Raymond Lindeman.",
            "options": None,
            "correctAnswer": "Lindeman's 10% Law: During energy transfer across trophic levels, only ~10% of total energy is stored as biomass at the next level; ~90% is lost as metabolic heat and respiration.",
            "explanation": "Limits the practical length of food chains in ecosystems typically to 4-5 trophic levels.",
            "topic": "Ecosystem & Ecology",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State the difference between In-situ and Ex-situ biodiversity conservation with two examples of each.",
            "options": None,
            "correctAnswer": "In-situ: Conserving species within natural ecosystems (e.g., National Parks, Biosphere Reserves). Ex-situ: Conserving endangered species outside natural habitats in protected environments (e.g., Botanical Gardens, Cryogenic Gene/Seed Banks, Zoological Parks).",
            "explanation": "In-situ maintains natural ecological and evolutionary dynamics; Ex-situ provides intensive human intervention for critically endangered taxa.",
            "topic": "Biodiversity Conservation",
            "marks": 2,
        },
    ],
    "mathematics": [
        # 1-5: MCQs (2 Marks each)
        {
            "type": "mcq",
            "questionText": "Evaluate the definite integral: ∫ from 0 to π/2 of (sin x / (sin x + cos x)) dx:",
            "options": ["A) π / 4", "B) π / 2", "C) 1", "D) 0"],
            "correctAnswer": "A",
            "explanation": "Using property ∫₀ᵃ f(x) dx = ∫₀ᵃ f(a-x) dx: 2I = ∫₀^(π/2) 1 dx = π/2 ⟹ I = π/4.",
            "topic": "Definite Integrals",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "What is the order and degree of the differential equation: [1 + (dy/dx)²]^(3/2) = k · (d²y/dx²)?",
            "options": [
                "A) Order = 2, Degree = 2",
                "B) Order = 2, Degree = 1",
                "C) Order = 1, Degree = 3",
                "D) Order = 2, Degree = 3"
            ],
            "correctAnswer": "A",
            "explanation": "Squaring both sides eliminates fractional powers: [1 + (dy/dx)²]³ = k² (d²y/dx²)². Highest derivative is 2nd order with degree 2.",
            "topic": "Differential Equations",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "If A is a square matrix of order 3 and |A| = 4, what is the value of the determinant |adj(A)|?",
            "options": ["A) 16", "B) 64", "C) 4", "D) 12"],
            "correctAnswer": "A",
            "explanation": "Formula: |adj(A)| = |A|^(n - 1). For order n = 3: |adj(A)| = 4^(3 - 1) = 4² = 16.",
            "topic": "Matrices & Determinants",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Find the angle θ between two vectors a = 2î + ĵ + 2k̂ and b = 3î + 2ĵ + 6k̂:",
            "options": [
                "A) cos⁻¹(20 / 21)",
                "B) cos⁻¹(14 / 21)",
                "C) cos⁻¹(18 / 21)",
                "D) π / 3"
            ],
            "correctAnswer": "A",
            "explanation": "a · b = (2)(3) + (1)(2) + (2)(6) = 6 + 2 + 12 = 20. |a| = √(4+1+4) = 3; |b| = √(9+4+36) = 7. cos θ = 20 / 21.",
            "topic": "Vector Algebra",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "In a binomial distribution B(n, p), the mean is 4 and variance is 3. What is the value of n?",
            "options": ["A) 16", "B) 12", "C) 8", "D) 20"],
            "correctAnswer": "A",
            "explanation": "Mean np = 4, Variance npq = 3 ⟹ q = 3/4 ⟹ p = 1/4. n(1/4) = 4 ⟹ n = 16.",
            "topic": "Probability Distributions",
            "marks": 2,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Evaluate the indefinite integral: ∫ (2x + 3) / (x² + 3x + 5) dx. Show step-by-step substitution.",
            "options": None,
            "correctAnswer": "Let u = x² + 3x + 5 ⟹ du = (2x + 3) dx. ∫ du / u = ln|u| + C = ln|x² + 3x + 5| + C.",
            "explanation": "The numerator is the exact derivative of the quadratic denominator, yielding direct logarithmic integration.",
            "topic": "Indefinite Integrals",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Find the general solution of the first-order linear differential equation: dy/dx + y·cot(x) = 2 cos(x).",
            "options": None,
            "correctAnswer": "Integrating Factor I.F. = e^(∫ cot x dx) = e^(ln sin x) = sin(x). Solution: y · sin(x) = ∫ 2 cos(x)·sin(x) dx = ∫ sin(2x) dx = -0.5 cos(2x) + C ⟹ y = -cos(2x)/(2 sin x) + C/sin x.",
            "explanation": "Standard linear form dy/dx + P(x)y = Q(x). Multiply by I.F. and integrate right-hand side.",
            "topic": "Differential Equations",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Find the shortest distance between the parallel planes: 2x + 3y + 4z = 4 and 4x + 6y + 8z = 12.",
            "options": None,
            "correctAnswer": "Dividing second plane by 2: 2x + 3y + 4z = 6. Distance d = |d₂ - d₁| / √(a² + b² + c²) = |6 - 4| / √(4 + 9 + 16) = 2 / √29.",
            "explanation": "Parallel plane distance formula d = |D₁ - D₂| / √(A² + B² + C²).",
            "topic": "3D Geometry",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Find the local maxima and minima for the function f(x) = 2x³ - 9x² + 12x + 5 using the second derivative test.",
            "options": None,
            "correctAnswer": "f'(x) = 6x² - 18x + 12 = 6(x-1)(x-2) = 0 ⟹ critical points x = 1, 2. f''(x) = 12x - 18. At x = 1: f''(1) = -6 < 0 (Local Maxima at (1, 10)). At x = 2: f''(2) = +6 > 0 (Local Minima at (2, 9)).",
            "explanation": "First derivative gives stationary points; sign of second derivative distinguishes concave down (maximum) from concave up (minimum).",
            "topic": "Application of Derivatives",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "State Bayes' Theorem formula for calculating conditional probability P(A_i | B) for mutually exclusive events A_1, A_2 ... A_n.",
            "options": None,
            "correctAnswer": "Bayes' Theorem: P(A_i | B) = [P(A_i) · P(B | A_i)] / [∑ (P(A_k) · P(B | A_k)) for k = 1 to n].",
            "explanation": "Allows updating prior probabilities P(A_i) to posterior probabilities given observed event B.",
            "topic": "Bayes Theorem",
            "marks": 2,
        },
    ],
    "computer science": [
        # 1-5: MCQs (2 Marks each)
        {
            "type": "mcq",
            "questionText": "In Python Object-Oriented Programming, what is the role of the '__init__' method?",
            "options": [
                "A) Constructor method to initialize newly created object attributes",
                "B) Destructor method to deallocate memory",
                "C) Class decorator method",
                "D) Static method executor"
            ],
            "correctAnswer": "A",
            "explanation": "__init__ is the initializer method automatically invoked when a class instantiation occurs.",
            "topic": "OOP in Python",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Which normal form in relational database design addresses and eliminates Transitive Functional Dependencies?",
            "options": ["A) Third Normal Form (3NF)", "B) First Normal Form (1NF)", "C) Second Normal Form (2NF)", "D) BCNF"],
            "correctAnswer": "A",
            "explanation": "3NF requires a relation to be in 2NF and have no non-prime attribute transitively dependent on the candidate key.",
            "topic": "Relational Databases",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "What is the worst-case time complexity of QuickSort when a poorly chosen pivot (e.g. smallest element each time) is used on sorted data?",
            "options": ["A) O(n²)", "B) O(n log n)", "C) O(n)", "D) O(log n)"],
            "correctAnswer": "A",
            "explanation": "Unbalanced partitioning in QuickSort produces an O(n²) worst-case recursion tree of height n.",
            "topic": "Algorithm Analysis",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "In computer networking, which protocol provides connection-oriented, reliable byte-stream transmission with flow and congestion control?",
            "options": ["A) TCP (Transmission Control Protocol)", "B) UDP", "C) IP", "D) ICMP"],
            "correctAnswer": "A",
            "explanation": "TCP establishes a 3-way handshake and handles sequence numbers, ACKs, and retransmissions for reliable delivery.",
            "topic": "Computer Networks",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "What does ACID represent in transaction processing systems?",
            "options": [
                "A) Atomicity, Consistency, Isolation, Durability",
                "B) Accuracy, Concurrency, Integrity, Distribution",
                "C) Authentication, Control, Identity, Data",
                "D) Allocation, Cache, Index, Directory"
            ],
            "correctAnswer": "A",
            "explanation": "ACID properties ensure database reliability: Atomicity (all-or-nothing), Consistency (rules maintained), Isolation (independent transactions), Durability (persisted commits).",
            "topic": "Database Systems",
            "marks": 2,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Explain the difference between Method Overloading (compile-time polymorphism) and Method Overriding (runtime polymorphism) with code examples.",
            "options": None,
            "correctAnswer": "Overloading: Multiple methods in the same class share the same name with different parameter signatures. Overriding: A subclass provides a specific implementation of a method defined in its superclass.",
            "explanation": "Overloading resolves at compile time; overriding resolves dynamically at runtime based on the instantiated object type.",
            "topic": "Polymorphism & OOP",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Write a Python function to implement Push and Pop operations for a Stack data structure using a standard list.",
            "options": None,
            "correctAnswer": "class Stack:\n    def __init__(self): self.items = []\n    def push(self, val): self.items.append(val)\n    def pop(self): return self.items.pop() if self.items else None",
            "explanation": "List append() and pop() operate at the top of the stack in O(1) amortized time, preserving LIFO ordering.",
            "topic": "Data Structures",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Given a SQL table 'Employees (emp_id, emp_name, dept_id, salary)', write a query to find the second highest salary without using LIMIT or TOP.",
            "options": None,
            "correctAnswer": "SELECT MAX(salary) AS Second_Highest FROM Employees WHERE salary < (SELECT MAX(salary) FROM Employees);",
            "explanation": "The subquery finds the global maximum; the outer query finds the maximum of all values strictly less than that maximum.",
            "topic": "SQL Queries",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the 7 layers of the OSI (Open Systems Interconnection) reference model in top-down or bottom-up order.",
            "options": None,
            "correctAnswer": "Layer 7: Application, Layer 6: Presentation, Layer 5: Session, Layer 4: Transport, Layer 3: Network, Layer 2: Data Link, Layer 1: Physical.",
            "explanation": "Conceptual framework standardizing communication functions across heterogeneous telecommunication protocols.",
            "topic": "Computer Networks",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the difference between Symmetric Key Encryption (AES) and Asymmetric Key Encryption (RSA).",
            "options": None,
            "correctAnswer": "Symmetric: Uses a single shared secret key for both encryption and decryption (faster, e.g., AES-256). Asymmetric: Uses a mathematically linked key pair: Public key for encryption, Private key for decryption (e.g., RSA-2048).",
            "explanation": "Symmetric requires secure key exchange; asymmetric enables public key distribution and digital signatures.",
            "topic": "Cybersecurity & Cryptography",
            "marks": 2,
        },
    ],
    "english": [
        # 1-5: MCQs (2 Marks each)
        {
            "type": "mcq",
            "questionText": "Identify the literary device used in: 'The wind whispered secret tales through the trembling autumn leaves.'",
            "options": ["A) Personification", "B) Hyperbole", "C) Oxymoron", "D) Onomatopoeia"],
            "correctAnswer": "A",
            "explanation": "Personification attributes human actions ('whispered secret tales') to non-human elements (the wind).",
            "topic": "Figures of Speech",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Choose the correctly punctuated compound-complex sentence:",
            "options": [
                "A) Although the storm was severe, we continued our journey, and we arrived safely at midnight.",
                "B) Although the storm was severe we continued our journey and we arrived safely at midnight.",
                "C) Although the storm was severe, we continued our journey; and arrived safely at midnight.",
                "D) The storm was severe, although we continued our journey and arrived safely at midnight."
            ],
            "correctAnswer": "A",
            "explanation": "A dependent clause starting a sentence requires a comma, and compound independent clauses joined by coordinating conjunctions ('and') require a comma.",
            "topic": "Sentence Structure",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "What is the meaning of the idiom 'To burn the midnight oil'?",
            "options": [
                "A) To work or study late into the night with diligence",
                "B) To waste energy carelessly",
                "C) To start a heated argument",
                "D) To destroy evidence by fire"
            ],
            "correctAnswer": "A",
            "explanation": "'Burning the midnight oil' refers to working or studying late into the night.",
            "topic": "Idioms & Phrases",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Identify the tone of an author who presents arguments objectively with empirical evidence and without emotional bias:",
            "options": ["A) Analytical and Objective", "B) Sarcastic", "C) Melodramatic", "D) Cynical"],
            "correctAnswer": "A",
            "explanation": "An objective, analytical tone presents facts, logical evidence, and balanced reasoning without personal prejudice.",
            "topic": "Reading Comprehension Analysis",
            "marks": 2,
        },
        {
            "type": "mcq",
            "questionText": "Which subjunctive modal correctly completes: 'It is essential that every delegate _____ in attendance on time.'",
            "options": ["A) be", "B) is", "C) was", "D) will be"],
            "correctAnswer": "A",
            "explanation": "The present subjunctive mood uses the base form of the verb ('be') following expressions of necessity or demand.",
            "topic": "Advanced Grammar",
            "marks": 2,
        },
        # 6-10: SAQs (2 Marks each)
        {
            "type": "saq",
            "questionText": "Convert the following direct speech into reported (indirect) speech: He said, 'I have completed my doctoral thesis this morning.'",
            "options": None,
            "correctAnswer": "He said that he had completed his doctoral thesis that morning.",
            "explanation": "Present perfect 'have completed' shifts to past perfect 'had completed', and temporal adverb 'this morning' shifts to 'that morning'.",
            "topic": "Direct and Indirect Speech",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Explain the concept of 'Dramatic Irony' in literature and provide one classic example.",
            "options": None,
            "correctAnswer": "Dramatic Irony occurs when the audience/reader knows vital information that the characters do not (e.g., in Shakespeare's Romeo and Juliet, the audience knows Juliet is under a sleeping potion, but Romeo believes she is truly dead).",
            "explanation": "Creates suspense, tension, and emotional engagement by giving the audience privileged foreknowledge.",
            "topic": "Literary Devices",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Write the essential format components of a formal Business Letter of Inquiry.",
            "options": None,
            "correctAnswer": "Sender's Address, Date, Receiver's Designation and Address, Subject Line, Salutation, Body of Letter (Introduction, Specific Queries, Call to Action), Complimentary Close (e.g., 'Yours sincerely'), Signature and Designation.",
            "explanation": "Standard formal communication layout follows clear structural hierarchy and professional etiquette.",
            "topic": "Formal Writing Skills",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Identify the clause type and grammatical function of the underlined part: 'What you decided yesterday will determine our project timeline.'",
            "options": None,
            "correctAnswer": "'What you decided yesterday' is a Noun Clause functioning as the Subject of the main verb 'will determine'.",
            "explanation": "A nominal clause acts as a noun; here it occupies the subject position of the sentence.",
            "topic": "Clauses and Syntax",
            "marks": 2,
        },
        {
            "type": "saq",
            "questionText": "Differentiate between 'Metaphor' and 'Simile' with one example of each expressing courage.",
            "options": None,
            "correctAnswer": "Simile: Explicit comparison using 'like' or 'as' (e.g., 'He fought as bravely as a lion in the battle'). Metaphor: Direct implicit comparison asserting one thing is another (e.g., 'He was a lion on the battlefield').",
            "explanation": "Similes state analogy explicitly; metaphors equate tenor and vehicle directly.",
            "topic": "Figures of Speech",
            "marks": 2,
        },
    ],
}


import re

def build_fallback_questions(
    board: str,
    subject: str,
    difficulty: str,
    ref_links: list[dict] | None = None,
    class_grade: str = "Class 3",
    limit: int = 5,
    force_mcq: bool = False,
) -> list[dict]:
    """Generates deterministic, grade-appropriate, subject-matched curriculum questions
    matching the exact question count requested across 3 distinct tiers:
    Tier 1 (Class 1-4): 5 MCQs @ 1 Mark = 5 Marks (KIDS_QUESTION_BANKS)
    Tier 2 (Class 5-10): 5 MCQs @ 1M + 5 SAQs @ 2M = 15 Marks (SECONDARY_QUESTION_BANKS)
    Tier 3 (Class 11-12 / NEET / IIT): 10 Questions @ 2 Marks = 20 Marks (SENIOR_SECONDARY_BANKS)
    """
    clean_subj = (subject or "General Assessment").lower().strip()
    clean_grade = (class_grade or "").lower().strip()

    # Accurate grade level classifier
    is_kid = False
    is_senior = False
    if any(k in clean_grade for k in ["neet", "iit", "jee"]):
        is_senior = True
    else:
        match = re.search(r'(?:class|grade)?\s*(\d+)', clean_grade)
        if match:
            cnum = int(match.group(1))
            if 1 <= cnum <= 4:
                is_kid = True
            elif cnum >= 11:
                is_senior = True
        elif any(k in clean_grade for k in ["primary", "kindergarten", "ukg", "lkg"]):
            is_kid = True
        elif any(k in clean_grade for k in ["senior", "higher secondary", "isc"]):
            is_senior = True

    # Determine bank category
    if is_kid:
        bank_map = KIDS_QUESTION_BANKS
    elif is_senior:
        bank_map = SENIOR_SECONDARY_BANKS
    else:
        bank_map = SECONDARY_QUESTION_BANKS

    matched_questions: list[dict] = []

    if "chem" in clean_subj:
        matched_questions = bank_map.get("chemistry", bank_map.get("science", []))
    elif "phys" in clean_subj:
        matched_questions = bank_map.get("physics", bank_map.get("science", []))
    elif "bio" in clean_subj or "botan" in clean_subj or "zool" in clean_subj:
        matched_questions = bank_map.get("biology", bank_map.get("science", []))
    elif "comput" in clean_subj or "code" in clean_subj or "it" in clean_subj or "ai" in clean_subj:
        matched_questions = bank_map.get("computer science", [])
    elif "math" in clean_subj or "algebra" in clean_subj or "calculus" in clean_subj:
        matched_questions = bank_map.get("mathematics", [])
    elif "eng" in clean_subj or "gramm" in clean_subj or "lit" in clean_subj:
        matched_questions = bank_map.get("english", [])
    elif "logic" in clean_subj or "reason" in clean_subj or "aptitude" in clean_subj:
        matched_questions = bank_map.get("logical reasoning", bank_map.get("mathematics", []))
    elif "social" in clean_subj or "hist" in clean_subj or "civic" in clean_subj or "geog" in clean_subj or "sst" in clean_subj:
        matched_questions = bank_map.get("social studies", bank_map.get("science", []))
    elif "sci" in clean_subj or "evs" in clean_subj:
        matched_questions = bank_map.get("science", bank_map.get("chemistry" if is_senior else "computer science", []))
    else:
        # Fallback based on tier
        if is_kid:
            matched_questions = bank_map.get("science", bank_map.get("mathematics", []))
        elif is_senior:
            matched_questions = bank_map.get("chemistry", bank_map.get("physics", bank_map.get("mathematics", [])))
        else:
            matched_questions = bank_map.get("science", bank_map.get("mathematics", []))

    if not matched_questions:
        if is_kid:
            matched_questions = KIDS_QUESTION_BANKS["science"]
        elif is_senior:
            matched_questions = SENIOR_SECONDARY_BANKS.get("chemistry", SENIOR_SECONDARY_BANKS["mathematics"])
        else:
            matched_questions = SECONDARY_QUESTION_BANKS.get("science", SECONDARY_QUESTION_BANKS["computer science"])

    # Assemble questions up to limit
    result = []
    pool = list(matched_questions)
    
    # If limit is larger than pool, cycle or generate parametric variants
    while len(result) < limit:
        for idx, item in enumerate(pool):
            if len(result) >= limit:
                break
            q_copy = dict(item)
            q_num = len(result) + 1
            q_copy["questionNumber"] = q_num
            q_copy["difficulty"] = difficulty
            if force_mcq:
                q_copy["type"] = "mcq"
                q_copy["marks"] = 1 if is_kid else (2 if is_senior else 1)
                if not q_copy.get("options") or len(q_copy.get("options", [])) < 2:
                    corr = q_copy.get("correctAnswer", "A")
                    q_copy["options"] = [f"A) {corr}", "B) Alternative Option B", "C) Alternative Option C", "D) Alternative Option D"]
                    q_copy["correctAnswer"] = "A"
            elif is_kid:
                # Class 1 to 4: 5 MCQs @ 1 Mark = 5 Marks
                q_copy["type"] = "mcq"
                q_copy["marks"] = 1
            elif is_senior:
                # Class 11 to 12: 10 Questions @ 2 Marks = 20 Marks
                # Respect individual question type (first 5 mcq, next 5 saq) with marks = 2
                q_copy["marks"] = 2
            else:
                # Class 5 to 10: 5 MCQs (1 mark) + 5 SAQs (2 marks) = 15 Marks
                if len(result) < 5:
                    q_copy["type"] = "mcq"
                    q_copy["marks"] = 1
                else:
                    q_copy["type"] = "saq"
                    q_copy["marks"] = 2
            result.append(q_copy)
        if not pool:
            break

    return result

