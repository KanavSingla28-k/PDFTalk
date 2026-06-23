import { render, screen } from '@testing-library/react'
import Page from './page'

describe('Home Page', () => {
  it('renders the brand name', () => {
    render(<Page />)
    expect(screen.getByText(/PDFTalk v2\.0 is now live/i)).toBeInTheDocument()
  })

  it('renders the main heading', () => {
    render(<Page />)
    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading).toHaveTextContent(/Chat with your documents/i)
  })
})
