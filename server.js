require('dotenv').config();
const express = require('express');
const mongoose = require('mongoose');
const multer = require('multer');
const path = require('path');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

/* ---------- Schema + indexes ---------- */
const postSchema = new mongoose.Schema({
  username: { type: String, required: true, trim: true, maxlength: 30 },
  caption:  { type: String, trim: true, maxlength: 300, default: '' },
  image:    { data: Buffer, contentType: String },          // photo stored inside MongoDB
  likes:    { type: Number, default: 0 },
  seeded:   { type: Boolean, default: false },          // true = sample post from scripts/seed.js
  comments: [{ username: String, text: String, createdAt: { type: Date, default: Date.now } }]
}, { timestamps: true });

postSchema.index({ createdAt: -1 });                 // home feed (newest first)
postSchema.index({ username: 1, createdAt: -1 });    // a user's profile feed
postSchema.index({ caption: 'text' });               // caption search

const Post = mongoose.models.Post || mongoose.model('Post', postSchema);

/* ---------- Connection (cached so it also works on serverless) ---------- */
let connecting;
async function connect() {
  if (!process.env.MONGODB_URI) throw new Error('MONGODB_URI is not set');
  if (!connecting) {
    connecting = mongoose.connect(process.env.MONGODB_URI, { serverSelectionTimeoutMS: 8000 })
      .then(() => Post.init());                      // makes sure indexes exist
  }
  return connecting;
}
app.use('/api', async (req, res, next) => {
  try { await connect(); next(); }
  catch (e) { connecting = null; res.status(500).json({ error: 'Database connection failed: ' + e.message }); }
});

/* ---------- Upload config ---------- */
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 4 * 1024 * 1024 },             // 4 MB (MongoDB doc limit is 16 MB)
  fileFilter: (req, file, cb) =>
    /^image\/(jpeg|png|webp|gif)$/.test(file.mimetype)
      ? cb(null, true) : cb(new Error('Only JPG, PNG, WEBP or GIF images are allowed'))
});

const wrap = fn => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);
const bad = (res, msg, code = 400) => res.status(code).json({ error: msg });
const validId = id => mongoose.isValidObjectId(id);

/* ---------- CRUD ---------- */
// CREATE
app.post('/api/posts', upload.single('photo'), wrap(async (req, res) => {
  if (!req.file) return bad(res, 'Choose a photo to upload');
  if (!req.body.username) return bad(res, 'Enter a username');
  const post = await Post.create({
    username: req.body.username,
    caption: req.body.caption,
    image: { data: req.file.buffer, contentType: req.file.mimetype }
  });
  res.status(201).json({ _id: post._id });
}));

// READ (feed, optional ?user= and ?q= caption search)
app.get('/api/posts', wrap(async (req, res) => {
  const filter = {};
  if (req.query.user) filter.username = req.query.user;
  if (req.query.q) filter.$text = { $search: req.query.q };
  const posts = await Post.find(filter).select('-image.data').sort({ createdAt: -1 }).limit(50).lean();
  res.json(posts);
}));

// READ (single post metadata)
app.get('/api/posts/:id', wrap(async (req, res) => {
  if (!validId(req.params.id)) return bad(res, 'Invalid id');
  const post = await Post.findById(req.params.id).select('-image.data').lean();
  post ? res.json(post) : bad(res, 'Post not found', 404);
}));

// READ (the photo itself)
app.get('/api/posts/:id/image', wrap(async (req, res) => {
  if (!validId(req.params.id)) return bad(res, 'Invalid id');
  const post = await Post.findById(req.params.id).select('image');
  if (!post || !post.image || !post.image.data) return bad(res, 'Photo not found', 404);
  res.set('Content-Type', post.image.contentType).set('Cache-Control', 'public, max-age=86400').send(post.image.data);
}));

// READ distinct creators/usernames list
app.get('/api/users', wrap(async (req, res) => {
  const users = await Post.distinct('username');
  res.json(users.filter(Boolean).sort());
}));

// READ user profile summary & aggregate stats
app.get('/api/users/:username', wrap(async (req, res) => {
  const { username } = req.params;
  const stats = await Post.aggregate([
    { $match: { username } },
    {
      $group: {
        _id: '$username',
        postCount: { $sum: 1 },
        totalLikes: { $sum: '$likes' },
        totalComments: { $sum: { $cond: [{ $isArray: '$comments' }, { $size: '$comments' }, 0] } },
        latestPost: { $max: '$createdAt' },
        firstPost: { $min: '$createdAt' }
      }
    }
  ]);
  const data = stats[0] || {
    _id: username,
    postCount: 0,
    totalLikes: 0,
    totalComments: 0,
    latestPost: null,
    firstPost: null
  };
  res.json({
    username,
    postCount: data.postCount,
    totalLikes: data.totalLikes,
    totalComments: data.totalComments,
    latestPost: data.latestPost,
    firstPost: data.firstPost
  });
}));

// UPDATE caption
app.put('/api/posts/:id', wrap(async (req, res) => {
  if (!validId(req.params.id)) return bad(res, 'Invalid id');
  const post = await Post.findByIdAndUpdate(req.params.id, { caption: req.body.caption || '' },
    { new: true, runValidators: true }).select('-image.data');
  post ? res.json(post) : bad(res, 'Post not found', 404);
}));

// UPDATE like / comment (atomic operators)
app.post('/api/posts/:id/like', wrap(async (req, res) => {
  if (!validId(req.params.id)) return bad(res, 'Invalid id');
  const post = await Post.findByIdAndUpdate(req.params.id, { $inc: { likes: 1 } }, { new: true }).select('likes');
  post ? res.json(post) : bad(res, 'Post not found', 404);
}));
app.post('/api/posts/:id/comments', wrap(async (req, res) => {
  if (!validId(req.params.id)) return bad(res, 'Invalid id');
  if (!req.body.text) return bad(res, 'Write a comment first');
  const post = await Post.findByIdAndUpdate(req.params.id,
    { $push: { comments: { username: req.body.username || 'guest', text: req.body.text } } },
    { new: true }).select('comments');
  post ? res.status(201).json(post.comments) : bad(res, 'Post not found', 404);
}));

// DELETE
app.delete('/api/posts/:id', wrap(async (req, res) => {
  if (!validId(req.params.id)) return bad(res, 'Invalid id');
  const r = await Post.findByIdAndDelete(req.params.id);
  r ? res.json({ deleted: true }) : bad(res, 'Post not found', 404);
}));

/* ---------- Demo endpoints for the teacher ---------- */
// Shows the index in use: look for IXSCAN and totalDocsExamined
app.get('/api/demo/explain', wrap(async (req, res) => {
  const plan = await Post.find().sort({ createdAt: -1 }).limit(10).explain('executionStats');
  const s = plan.executionStats;
  res.json({ nReturned: s.nReturned, totalDocsExamined: s.totalDocsExamined, executionTimeMillis: s.executionTimeMillis,
             winningPlan: JSON.stringify(plan.queryPlanner.winningPlan) });
}));
app.get('/api/demo/indexes', wrap(async (req, res) => res.json(await Post.collection.indexes())));
// Shows replication: replica set name, primary and members
app.get('/api/demo/replication', wrap(async (req, res) => {
  const h = await mongoose.connection.db.admin().command({ hello: 1 });
  res.json({ setName: h.setName, primary: h.primary, hosts: h.hosts, isWritablePrimary: h.isWritablePrimary });
}));
app.get('/api/health', (req, res) => res.json({ ok: true, db: mongoose.connection.readyState === 1 }));

/* ---------- Errors ---------- */
app.use((err, req, res, next) => {
  if (err.code === 'LIMIT_FILE_SIZE') return bad(res, 'Photo is larger than 4 MB');
  bad(res, err.message || 'Something went wrong', err.name === 'ValidationError' ? 400 : 500);
});

module.exports = app;
module.exports.Post = Post;
if (require.main === module) {
  const port = process.env.PORT || 3000;
  app.listen(port, () => console.log(`Frame running on http://localhost:${port}`));
}
