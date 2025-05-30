import unittest
from app import app, todos # Import app instance and todos list

class TodoAppTests(unittest.TestCase):

    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        # Reset the todos list before each test for isolation
        todos.clear() # Use .clear() method for lists

    def tearDown(self):
        # Ensure todos is cleared after tests if needed, though setUp should handle it for each test
        todos.clear()

    def test_initial_page_empty(self):
        """Test that the main page loads correctly and shows 'No to-dos yet!' when empty."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"My To-Do List", response.data)
        self.assertIn(b"No to-dos yet!", response.data)

    def test_add_todo_item(self):
        """Test adding a new to-do item."""
        # Add a first item
        response_add = self.client.post('/add', data=dict(todo='First test todo'), follow_redirects=False)
        self.assertEqual(response_add.status_code, 302) # Check for redirect
        self.assertEqual(response_add.location, '/') # Check redirect location

        # Verify item is on the page
        response_get = self.client.get('/')
        self.assertEqual(response_get.status_code, 200)
        self.assertIn(b'First test todo', response_get.data)
        self.assertNotIn(b"No to-dos yet!", response_get.data)

        # Add a second item
        response_add_2 = self.client.post('/add', data=dict(todo='Second test todo'), follow_redirects=False)
        self.assertEqual(response_add_2.status_code, 302)

        response_get_2 = self.client.get('/')
        self.assertEqual(response_get_2.status_code, 200)
        self.assertIn(b'First test todo', response_get_2.data)
        self.assertIn(b'Second test todo', response_get_2.data)

    def test_remove_todo_item(self):
        """Test removing a to-do item."""
        # Add an item first
        self.client.post('/add', data=dict(todo='To be removed'))

        # Verify it's there
        response_get_before_remove = self.client.get('/')
        self.assertIn(b'To be removed', response_get_before_remove.data)

        # Remove the item (it will be at index 0)
        response_remove = self.client.get('/remove/0', follow_redirects=False)
        self.assertEqual(response_remove.status_code, 302)
        self.assertEqual(response_remove.location, '/')

        # Verify item is removed
        response_get_after_remove = self.client.get('/')
        self.assertEqual(response_get_after_remove.status_code, 200)
        self.assertNotIn(b'To be removed', response_get_after_remove.data)
        self.assertIn(b"No to-dos yet!", response_get_after_remove.data)

    def test_remove_multiple_todo_items(self):
        """Test removing specific items when multiple exist."""
        self.client.post('/add', data=dict(todo='Item 1'))
        self.client.post('/add', data=dict(todo='Item 2'))
        self.client.post('/add', data=dict(todo='Item 3'))

        # Remove "Item 2" (index 1)
        self.client.get('/remove/1')

        response = self.client.get('/')
        self.assertIn(b'Item 1', response.data)
        self.assertNotIn(b'Item 2', response.data)
        self.assertIn(b'Item 3', response.data)

        # Remove "Item 1" (now at index 0)
        self.client.get('/remove/0')
        response = self.client.get('/')
        self.assertNotIn(b'Item 1', response.data)
        self.assertNotIn(b'Item 2', response.data)
        self.assertIn(b'Item 3', response.data)


    def test_remove_non_existent_todo_item_out_of_bounds(self):
        """Test attempting to remove a to-do item with an out-of-bounds index."""
        self.client.post('/add', data=dict(todo='Existing Item'))

        # Attempt to remove an item at a non-existent large index
        response_remove = self.client.get('/remove/100', follow_redirects=False)
        self.assertEqual(response_remove.status_code, 302) # Should redirect gracefully
        self.assertEqual(response_remove.location, '/')

        # Verify the original item is still there
        response_get = self.client.get('/')
        self.assertIn(b'Existing Item', response_get.data)
        self.assertNotIn(b"No to-dos yet!", response_get.data)

    def test_remove_non_existent_todo_item_empty_list(self):
        """Test attempting to remove from an already empty list."""
        # Ensure list is empty
        self.assertEqual(len(todos), 0)

        response_remove = self.client.get('/remove/0', follow_redirects=False)
        self.assertEqual(response_remove.status_code, 302)
        self.assertEqual(response_remove.location, '/')

        response_get = self.client.get('/')
        self.assertIn(b"No to-dos yet!", response_get.data)

    def test_add_empty_todo_item(self):
        """Test adding an empty string as a to-do item."""
        # In the current app.py, an empty string is added.
        # If this behavior were to change (e.g., to prevent adding empty todos), this test would catch it.
        response_add = self.client.post('/add', data=dict(todo=''), follow_redirects=True)
        self.assertEqual(response_add.status_code, 200)
        # Assuming empty string todos are displayed as empty <li> tags or similar.
        # The current app.py does NOT allow adding empty todos due to `if todo:`.
        # Let's check that the count of todos has not increased.
        self.assertEqual(len(todos), 0)
        # Consequently, the page should still show "No to-dos yet!"
        self.assertIn(b"No to-dos yet!", response_add.data)
        self.assertNotIn(b'<a href="/remove/0"', response_add.data) # Check that no remove link for item 0 is present


if __name__ == "__main__":
    unittest.main()
