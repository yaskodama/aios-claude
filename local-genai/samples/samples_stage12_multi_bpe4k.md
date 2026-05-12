# Sample generations — stage12_multi_bpe4k
Checkpoint: `transformer_stage12_multi_bpe4k.pt` (1,709,440 params, bpb 1.6672, ≈ ppl/byte 3.176)
Tokenizer: `tokenizer_stage12_multi_bpe4k.json` (vocab 4096, ≈ 3.16 bytes/token)
The model is a Transformer (depth=6, d_model=128, RoPE) trained
on 10 MB of Shakespeare + King James Bible through a 2048-vocab
byte-level BPE tokenizer. It is NOT an instruction-tuned chatbot
— it continues whatever input it is fed, in the same Early
Modern English style as its training data.

Each prompt is run at three temperatures (0.6, 0.85, 1.05), targeting ~320 characters of continuation with seed 7.

## 1. `To be, or not to be,`
### temperature 0.6
```
To be, or not to be,
Dear, and so lordly, for the world, it is,
To do this, and to give it me to speak

   Ser. My lord, in Purgatory,
I am not the king’s in Louis Purgatory

   Ser.

   Ser. Not much, but I

   Ser. Nor so much, but with me

   Ser. Ape, I say, I say, my Lord,
The Countess of Bly hath made my welcome.
  Shake, I warrant
```
### temperature 0.85
```
To be, or not to be,
Dear Madam, and so tea for me.
What, is’t thou, baleelle?
Would you to batch himback?
I cannot travail first, but forgotten,
Are you sure mass Phoebus? Will you be so?
That I?

LAUNCELET.
O mute, I do pray you, if you go in the court,
And I will say, my dear madam,
I am almost as liar as thou hast not.
  I am not, mer
```
### temperature 1.05
```
To be, or not to be, thehath is not so very
happy in Courne it, let not lament this bouncer."

Wailing to the Soulback, we slighted trailing prove they had set down
their stri OFSECOND PROVE
hence, did not stir if the cat? Not much in the matter
That that evening of his predisength
Took placefer shot they in the court,
Fifteen days youth,
```

## 2. `All the world's a stage,`
### temperature 0.6
```
All the world's a stage,
The same--the same, and the same, and the same,
The same, the baleful, the same, and the other
Whose great-coat in the world is first said
To be the same,
The same man is a man, and then the same,
The same, the same?


I.

CONCERJWICS.
Ile be merciful in the world,
And I am for the same thing.

CONTANIO.
What, or what
```
### temperature 0.85
```
All the world's a stage, the life
Our mind's God, for prayers, it befits linkless bounce."

While the marriage was from the great East to the Pox first, the ungoverned
people who were acquainted had deprived the principal machinations of
itself, the Eastlands were confined, and the White Coveria Methodist.

The Bastille married for the last six
```
### temperature 1.05
```
All the world's a stage,'shatch--it's all
 tea for me to play it, tres link husky enough."

Wailing to the breakfast onlyback, we slighted trailing down the plain
house while the striking is in time to taste Phoot-Hhen. Sheding up
and up? Not much in the way--the straits of his palletengthed lip
ferves the way in the business to hide his grey
```

## 3. `ROMEO. `
### temperature 0.6
```
ROMEO.  First
Osborne's name, in the name of a generous man,
While he was a man of the righteous
Whose name is a man in Purgatory,
With whom he had been a gentleman in his name

   Macd. This same did,
The more I did, in his faith, that my Lord
Aught I should say,

   Macd. I saw the Master,
And I with his youth,
He did not know
```
### temperature 0.85
```
ROMEO.  [_Draws his] You are a man of the greatest Israel
documents, as a man said, “Would you receive a secret?”back, weighed
away first, and then began to strike himself in time to taste a very
casual sort of thing that had been starvation; but in the end of my
time, I pressed my hand to do my best; and, they said, a cop
```
### temperature 1.05
```
ROMEO.  [_Drove._] Kymain, be a public play it, let’s
 hush the snake requiring to raise to the breakfast onlyback, simply in
examinement presented to the striking gentleman in both antis Phoebus road.
I remember talked if the cat? Not much in the matter--that is all those
who should loveengthly do!

ROSALINE.
So I believe it
```

## 4. `Call me Ishmael.`
### temperature 0.6
```
Call me Ishmael.

WOOER.
I say, Malcolm!

WOOER.
I am not a fool, I am not mad.

COSTARD.
I thank you, sir.

WOOER.
I have a woman, sir, as I am; I hear her, and I am not a woman,
Erinch.

COSTARD.
I am not married to her, sir.

COSTARD.
What, sir?

COSTARD.
Who, sir?

COSTARD.
No, sir, I have a doublet and a battered, for it is a great
```
### temperature 0.85
```
Call me Ishmael.

WOOER.
I say, Malyr, what louis!

CRESSIDA.
Whoseback is the slight in traitor,
With ungoverned trial in him?

DON JOHN.
I had no more tongue?

CRESSIDA.
Happy, sweet man,
Thou art the good way in the court to hide,
Which for the worms of the most prudent
Consistent with thine eyes.

DON JAD justice being so,
And so again
```
### temperature 1.05
```
Call me Ishmael. [_He went._] Keep.)_ tea for me.
What, trespass? husk’d herray?
Henry baggageback, simply in traffic first,
Zoe when strike is in him anticipate,
Hhenionel did mock if priest had?

LAUNCELET.
O mockengthly,
Thou vp the way in the court to hide,
Which for the last further madness
You choosecomeointed searchingke:
’
```

## 5. `It was the best of times,`
### temperature 0.6
```
It was the best of times, the most
familiar of the world, that I ever saw, was linked in the same
procession.

In the meantime, the slightest tragedy, and the ungoverned,
cultivated, and depicted, and invented, was the only judge of the
mode of that man, and, for the purpose of being cursed, gave him a
momentary silence, and with great delight
```
### temperature 0.85
```
It was the best of times, the most
familiar of tea in the world, it was tied loose to baggage, but it was
quite not to beback, but to dismiss itself.

With these mischievous incom hairy tight depths which were invented in
the cathedral walk, the man saw that there was a pallor of a lily
candle, and then a tall, inclusive sort of cheek, and sil
```
### temperature 1.05
```
It was the best of times, the Indian
entirely existing tea for the public play it, and the lac husky who was
taken and poorer from himback, simply in traffics first broke up.

What had he induced anticipation deprivedhen William General of �gge?
That in the end of the three evening of his retires he was utterly
ndamed.

In the maladabouts Ets
```

## 6. `Four score and seven years ago`
### temperature 0.6
```
Four score and seven years ago, when
she was at home, she said, “I am sorry to see her.”

“And why should she be so kind to me to?”

“I cannot tell her.”

“I have not been a gentleman in my house.”

“You are not a man, but you have not had a woman in your house.”

“Surely, you have been a woman of a woman, too, and I know that
```
### temperature 0.85
```
Four score and seven years ago, when
she was still standing there, in the evening, it was tied loose, as
though her eyes were to raise to the room only, and her slight inconnection
with herself.

What had he induced him to tempt the girl with which she had just
watched up? Not much in the way of landlord’s being pressed to gratify
herbs; and the way
```
### temperature 1.05
```
Four score and seven years ago, when
she started at once.)_ tea for me. Hyp, Rodha huskie, give me some to your
daughter from onlyback, simply in traffics first, presented me on stri OF
EAR anticipation deprived of you.... But why talked if you had? Not much
to say--that that evening, with pickled gratitude for your
fervourhood in the business to hide
```

## 7. `In the beginning`
### temperature 0.6
```
In the beginning, I
felt that I had been in the world, it was not for the one to whom I
could be killed to speak.

I only saw that the slight and unexceptionable vicissitude of my soul
was a man who had been deprived of a man who had had a woman who had
been in the world, and that there was a physician in the world.

We had a magistrate
```
### temperature 0.85
```
In the beginning, when
O!

L tea for me. O it, let me looke!

LYSET.
You think I only did, that slight in my eyes prove they,
I’ll strike them in time.

DON JOHNE.
He hath not had?

LAUNCELET.
O mute, I do pray you, if you go in the court,
And I will say, my dear madam,
I am almost as liar as thou hast not.

LADY JOHN.
O, what more shall
```
### temperature 1.05
```
In the beginning,hath--it’s
 tea-time. Hつ, tower loo husky, cough!"

"You thinky onlyback, simply in traffics first, presented it when you are
brought down here, what deprivation does you know? why talked if you had?
You hear the word--the same--and what's become of gratitude for your
fervent attention they don Crisphereabouts? Yes
```

## 8. `Blessed are the meek,`
### temperature 0.6
```
Blessed are the meek, the word of God, the
injurious of the Israel, the God of Israel, the God of Israel, the God of
thy brothers, the God of Israel, and the God of Israel, the God of Israel,
and the man of Israel, and the man of Israel, and the man of God, and
the man of God, and the man of God, and the man of God, and the man
of Israel, and
```
### temperature 0.85
```
Blessed are the meek, thehath of the world's
tempests it, and the lot of baleellred sanctum poore to the land of the
Holy Ghost, so they call the strife is in him."

"I say then, you know I have talked if you had? Not much in the matter
that I eat of you, for I have been thinking of you," Alice assumed,
shaking her head with great delight,
```
### temperature 1.05
```
Blessed are the meek, thehath of Kent's
 tea for Cock, it generates divides
While the Dame is banished and poore to ourback,
The inconn prove they plainly ungoverned,
Are we anticipated, and then live down,
When talked if the city? Not much in the stand
Of that evening, what's this terrible Whitold
Thou vp the way in Crisal to hide,
Which for
```

## 9. `Please explain the use of artificial intelligence in education.`
### temperature 0.6
```
Please explain the use of artificial intelligence in education.




CHAPTER III—FOURSE


Again the balance of the banquet

Again the great and universal tragedy

The unfortunate strife is induced to taste the contemplation of the
ticheies of the rival.

The second, that the first, however, has been a very curious
compliment in the court, and that it may be the last thing to be
t
```
### temperature 0.85
```
Please explain the use of artificial intelligence in education.
He went to bed, and there tea-time had been a generous silence louder
with the cough of the races to the breakfast-back, the slight inconnection
of the unfortunate striking gentleman in the antique, waiting for
the young man, who had been stoutly blundering the lock. This evening,
Judge Pocket curndure, was a singly mal
```
### temperature 1.05
```
Please explain the use of artificial intelligence in education.
He went with a sense of intention for the public mind it, tied louder
with the citizens and panic from onlyback, simply in traffics first
relinquished by a rascality mass Purgatory in Chenildeou, talked if the
? Not much in the matter of landlations thereand with popularists of liquor
and good they wished each malador
```

## 10. `Describe how a transformer neural network works.`
### temperature 0.6
```
Describe how a transformer neural network works.
Descending to the palace in the public, it is plainly loosened by the
same ‘Holland,’ from the great-coat in the cart, and the ungoverned
crazy mass, which he throws in a glass of water in the starboard.

‘How do you think of this, sir?’ said Mr. Pickwick.

‘I don’t know,’ replied Ralph, ‘that it is not
```
### temperature 0.85
```
Describe how a transformer neural network works.
Descending the course of tea in the evening, it comes to the lac husky
reds of the races to the breakfast-back, the slight inconnection with
the ungoverned tribe in its antisprit, and then the grove betokened with
the blundering, the playful-gandowed pallet of colours curdy them.

In the court, down into Episcopal, the
```
### temperature 1.05
```
Describe how a transformer neural network works.
Dawn Kate's pal tea for Caly it, trespass'd husky, herray of vanished
driven onlyback, her slight in traffic first, so ungoverned, till in time antis
V depriven the following armtic of �gv? Not much in the way of landlations
and tyranny.




ROSALINE
anceabout including us like a thing madness to taste, and therefore
```

## 11. `Write a short poem about autumn rain.`
### temperature 0.6
```
Write a short poem about autumn rain.

WOOER.
I say, with an audacious lion,
And I said, “Would you have a single man
That weighed with the man, and so they’d strike
The pot of Purgatory in the winter,
When you came to your house, you would have me

   Wandering.
Go to, I pray you.

   W. Souls, thou wilt, I thank you,
I am not so afraid of you.

   W
```
### temperature 0.85
```
Write a short poem about autumn rain.
Dear Madam, I have tea for a minute, it comes trespassing to bite
the broom to your own marriage. See, madam, in traitor first, why,
except I am in love for a title of yore. I am not in my house. Nor is
it mine, nor my heart. But what are you going to do with your
candlesticks? Souls, old woman, my dear madam, have ch
```
### temperature 1.05
```
Write a short poem about autumn rain. [_He went._] Keep.)_ tea for me.
What, trespass? husk’d herray? How ragged to think from himback?
 slight in traffic first, presented in the stri OFSACUS OF REVERNEhen.
She was talked if she had? Not much in the way of my act eatandaking,
Everly yesterday.

[_Draws a tallabout includ married woman, whither she goes._]
```

## 12. `吾輩 は 猫 で ある 。`
### temperature 0.6
```
吾輩 は 猫 で ある 。

お 母 さま は 、 お 母 さま の お 嬢 さん が 聞き立っ て 、 どう し て も 、 秋 の 上 へ 、 倒 だけ は 、 お 悪い 。 あの 時 三 日 に 、 ただ 感じ の 前 へ 来 た と 思っ たら 、 手 に 赤 シャツ が 赤 シャツ も こっち へ 行っ て 、 そ
```
### temperature 0.85
```
吾輩 は 猫 で ある 。 しかし 守頃 が 背細く 感じ が hushing Helleillen to your own
mind?”

The slight dismissal of the plain presented itself on the box, in
intermediately, depicted in a glass of water, if not in?





CHAPTER XIV—JEE PROTIEGRODES


The post including of the scout had got to the chimney-piece, and began
the
```
### temperature 1.05
```
吾輩 は 猫 で ある 。 しかし 守産 に � tea in prayers, it comes tres louder and
predestine to your own marriage than to our great ignorance to dismiss itself
will be presented while the strife is induced anticipation deprivedhen you
tell of meaning as we judge; much in the matter of my actionsand, how
Everly for curiosity and goodness
```

## 13. `メロス は 激怒 し た 。`
### temperature 0.6
```
メロス は 激怒 し た 。




















































「























「 なに 、 意�y








「 私 は 、 お 母 さま の 前 さん が 、 お そりゃ 、 どこ の 下 に 電車 に 赤 シャツ と 云う 」

「 なん と も 思う と 、 私 は 貸し た の は 、 お 母 さま
```
### temperature 0.85
```
メロス は 激怒 し た 。 しかし 守頃 が 背細く 意味 を 翻しい 事件 が 、 映っ た まま で 、 独仙 は 、 その 時 校長 偶然 細 愛 と いっ て 、 苦笑 し ながら 愛図 な 煙草 で ある 、 と お 母 さま こと に 、 小説 の 千上 の 下 に � perfectly likely to
 mer justice から
```
### temperature 1.05
```
メロス は 激怒 し た 。 御hatcoent� さん に � tea-time.
つくっKげ て hushing size on the banks and panic from thebacks simply in
examinements presented while the striking is induced anticipation deprivedhen.
It was talked with more than ever; much in the matter of landlordicalanda,
Everington curndure.

In the court,about includ
```

## 14. `国境 の 長い トンネル を 抜ける と`
### temperature 0.6
```
国境 の 長い トンネル を 抜ける と 、 割色 が 起き たい 。

「 あなた は 、 もう 、 あなた が 、 映っ たら 、 お 地女 の 細い 悪い 。 あの 時 三 日 に 、 たのに 海板 に は 、 ただ こんな に 手前 に 、 山嵐 は 、 お 家 に お 母 さま の 思い流 に 、 そんな 事 を 言い�
```
### temperature 0.85
```
国境 の 長い トンネル を 抜ける と 御hatけい しびり tea in the evening,” said
Milady, hushing himself who was about to speak.

“Whoseback is the slightest tragedy first, presented in the yard?”

“Oh, what a strange thing! Will that be so simple!” said Militant
Cassius. “Sandy, mocking,” said shending the attention of the magistrate

```
### temperature 1.05
```
国境 の 長い トンネル を 抜ける と 御hatcogn� さん と � tea 30 aclo it
reality.—having baggage said about this to your ladyship’s only
forget slight in traffics first perched on the page OF SACUSO, Point,
ashen-gardening talked if you had? Not much in the matter of my own
and my pupilength is liablendure. Now they don’t come down.”

I prop
```

## 15. `むかし むかし ある ところ に`
### temperature 0.6
```
むかし むかし ある ところ に は 、 実際 生徒 （ はしご ） が 書い て 、 おれ の 事 が 、 映っ たら 、 しかに 私 の 胴 の 角 を お 嬢 さん に 聞え たら 、 細君 の 落ちつかぶらい た から 、 それ で も 、 どう し て しまい に 肩 に 、 理由 も こっち へ 行っ て 、 そ
```
### temperature 0.85
```
むかし むかし ある ところ に は 、 守頃 が 胃線 せ ば 、 この � hushingぐっしい 、 それ は 、 おれ から なる と 一 つ slightし て 、 独仙 は 、 その 時 校長 偶い て み たら 、 愛外 は ない と って 、 ただ こう いう 手 に 走っ て しまい に 肩 に 、 火事 を ここ に �
```
### temperature 1.05
```
むかし むかし ある ところ に はhatcogn Kooddownin tea for a wife, it
was divided by an easily scentred victim to raise marriage with the only
for her slight inconn prove they had presented it when striking
Each anticipation deprived which William did not talked if the cat? Not
it might be said, that there was rather worth pawning in words—

    
```

## 16. `私 は 日本 から 来 ました 。`
### temperature 0.6
```
私 は 日本 から 来 ました 。 しかし 私 の 国経 （ ば いつ ） の よう に 出 た 。

「 おれ は 一 つ の 、 映っ たら 、 おれ の 人 の 胸 の 角屋 から 始め て いらっしゃる 意味 は ない 。 おれ の 前 に 、 手前 に 痛み で も 極 （ き ） め て いる の です 。 おれ は
```
### temperature 0.85
```
私 は 日本 から 来 ました 。 しかし 守者 が 背行 （ そろ ） が hushed量史 （ けいべん ） を し て おろし 、 私 の 胴紙 を 渡し て 、 偶然 細 愛 と いっ て 、 苦笑 し ながら 愛図 な しき と は 肩 に 、 火鉢 を 思っ て 、 使う そりゃ 、 どんな 奴 も � perfectly likely
```
### temperature 1.05
```
私 は 日本 から 来 ました 。 しかし 守産 に � tea-time.
つ gener�K.—having bought the citad to London!—let him breakfast?”back
The slight dismissal prove they had set down while the striking
city anticipated, and thenhen.

When talked � いる 」? Not much in the matter of landlations--and what
fledues haveoccover made them sh
```

## 17. `桜 の 花`
### temperature 0.6
```
桜 の 花 は 、 我々 に 生き て み たら 、 私 は 、 あの 男 で も 、 おれ の 事 が 、 映っ たら 、 しかに 私 の 胸 の 触 水 が 、 あの 時 三 日 に 、 たのに 浮べる 苦笑 し た 手紙 を 、

「 春 の 前 、 火事 も こっち へ 行っ て 、 そんな 事 を 聞
```
### temperature 0.85
```
桜 の 花�hat� の 国 が 踏み士 の よう に 出席 し たら 、 それ は 、 おれ から なる と 一 つ slightさい と 、 私 の 路 で は ない の だ 。

 Purgatory!

When we did so, if we had any influence in each other, we saw that there
was something so much gratpanied in the public.

In the course
```
### temperature 1.05
```
桜 の 花�hat� の 国 が 踏籠 せ ば 、 この あ hus calm折 は 、 それ から 、 服裞 （ ち slightST tra�に first beneath herself.

What are they induced ant mass Purgatory to 三 日 毎� talked if the
Mediots or the Locellical Bill, or the White Coveria Methodemes Crispe to
hearten with those youths
```

## 18. `雨 が 降る 。`
### temperature 0.6
```
雨 が 降る 。




徒 は 、 お 母 さま の お 嬢 さん が 、 自分 の お 辞 が 、 映っ た まま 、 お 父 さん の 猫 を お 悪い 。 動く の は とうてい 感じ の よう に 、 苦笑 し た 手紙 を 増き 出し て 、

「 そう か 、 おれ も 、 お 嬢 さん に 、 そんな 事
```
### temperature 0.85
```
雨 が 降る 。 しかし 、 あなた に 生き て み たつく の 自分 は 、 それ から 人間 と いう 事令 が 、 映っ た まま 、 それ なら 、 倒 だけ は その 時 校長 偶い て み たら 、 愖 （ いま ） い 苦笑 し な 手 を 起し て しまっ て 、 買い から お 母 さま
```
### temperature 1.05
```
雨 が 降る 。 御hatcoent� さん に � tea-time.
つ generous divisionhant baggage was required to raise to the breakfast
back into the slightest traffic first, presented to the stri OF
EAR anticipation deprived of William General of �gv? Not much
acquisition.

Having seated himself in a liablende case, they returned abstracted
```

## 19. `Hello, world! こんにちは 世界 !`
### temperature 0.6
```
Hello, world! こんにちは 世界 !




CHAPTER III—FOUR HOUT DAYSS


During the first pages of the only land, the slightest tragedy of the
sentiments, is induced to keep a very different way of waking into the
ground of the rivers.

The second day, the first day, when the first of the sixth night was
daining the fourth of the East Indians, the second
```
### temperature 0.85
```
Hello, world! こんにちは 世界 !
hath seen me so that there is one who is an ital,
Aha!

CADE.
No, not to be

ANISTAL.
 first, good sir,
What’s in me?

DON JOHN.
I had no more tongue?

CAIUS.
Ay, ay, for I will not do anything
To be good they say then.

DON JOHN.
All my taste, and therefore I do speak of.

CAfort perfectly well.

DON PAGE.
How now!
```
### temperature 1.05
```
Hello, world! こんにちは 世界 !
hatcognitor of God, be prayers, it generates! lament husky who said
them to your father to die from himback, simply in traffics first, presented
their strife till in time anticipation, in order not to arm over your
shoulders that? Not much in the matter of my act eatand wine, for Iength
occurnd them. Now they don’t come
```

## 20. `1, 2, 3, 4,`
### temperature 0.6
```
1, 2, 3, 4, adding to the
      ‘Humphrey, 2, 170, 276, 1775, p. 28, 276, 275.

      “The ‘Autembrity’ _Professor_ (a-son) is the first of the
      “Spaniard’s”), and the Pyramidia (poor Pyotr Petrovitch),
      commenced the most ingenious and severely responsible
      romance, the justice of the Pyramus, and the
```
### temperature 0.85
```
1, 2, 3, 4, adding to the ports of
 tea for the public, it was tied loose to bathe her right arm to raise
her hands only in her lungs to the ground, and set down the pool to
fall. The mass tightened in the road towards the sheet of the priest’s
pocket, and saw that there was a pickled picture with curiosity.

In the court, as I
```
### temperature 1.05
```
1, 2, 3, 4, adding to this case, had
 tea for Cuba Israel, tied loo huskily into her broom to raise to the
horse, simply in traffic first, presented it to stri OFSACUSOUS PAGE
hence, did not stir if the cat? Not much in the matter of my act eatand,
fled in a lilynd; gave it they wished each malador including us, whither
it was pr
```
