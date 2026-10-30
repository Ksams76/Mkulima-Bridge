# UI refinement: restored farm background and moving slogan

This update builds on the professional sidebar dashboard. It restores the existing `frontend/images/shambasense.jpeg` farm image as the page background, uses it again in the welcome panel with a readability overlay, and adds the original ShambaSense slogan as a continuous right-to-left ticker beneath the top bar.

- No backend files or database schemas were changed.
- All existing frontend IDs, forms, navigation links and JavaScript files were preserved.
- The ticker pauses on hover and respects reduced-motion preferences.
- The mobile layout switches the background attachment to scroll for smoother performance.

To apply, replace only the `frontend` folder in the current project with the `frontend` folder from this package. Keep `.env`, `backend`, `.venv` and the local database untouched.
