import { render, screen } from '@testing-library/react'
import Page from './page'

describe('Home Page', () => {
  it('renders the Next.js logo', () => {
    render(<Page />)
    
    const logo = screen.getByAltText('Next.js logo')
    expect(logo).toBeInTheDocument()
  })

  it('renders the getting started text', () => {
    render(<Page />)
    
    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading).toHaveTextContent('To get started, edit the page.tsx file.')
  })
})
